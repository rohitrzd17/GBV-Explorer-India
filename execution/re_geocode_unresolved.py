"""
Execution script: Re-geocode unresolved incidents and purge foreign reports.

High-accuracy, high-performance engine:
1. Strict India vs Foreign classifier (filters out US/UK/Aus/foreign crime reports)
2. Comprehensive Indian Localities & Metropolitan Suburbs (Maujpur, Ghatkopar, NCR, etc.)
3. All Indian Districts & Cities down to 4-letter names (Pune, Agra, Gaya, Beed, Kota, Puri, etc.)
4. State Police Force attribution (Delhi Police, UP Police, Mumbai Police, etc.)
5. Judicial & Legal Jurisdiction attribution (Supreme Court, High Courts, POCSO/CJI benches)
6. Major nationwide GBV cases (Moving bus gang rape -> NCR, Sandeshkhali, RG Kar, Hathras, etc.)
7. Auto-exports static JSON/CSV for GitHub Pages
"""

import os
import sys
import re
import html
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from execution.geocode_locations import load_gazetteer
from execution.database import get_connection
from execution.export_static import export_static_data

# ---------------------------------------------------------------------------
# 1. Foreign indicators – comprehensive detection of non-Indian stories
# ---------------------------------------------------------------------------
FOREIGN_OUTLETS_AND_DOMAINS = [
    r"\b(cbs news|nbc news|abc news|fox news|bbc|cbc|cnn|reuters|ap news|the guardian)\b",
    r"\b(washington post|new york times|los angeles times|chicago tribune|the hill|rolling stone)\b",
    r"\b(variety|hollywood reporter|rnz|stuff\.co\.nz|stripes\.com|military\.com)\b",
    r"\b(wpsd|wpta|fox59|delco times|fresnobee|cleveland\.com|wkyc|ksnv|wral|witn)\b",
    r"\b(applevalleynow|rocketcitynow|newscentermaine|wsoc|wkyt|wcti|wciv)\b",
    r"\b(king5|wjla|fox40|wwltv|ktul|krem|kmph|kark|wowt|wmar|wftv|wcnc|wbma|wbff|wbal|wafb)\b",
    r"\b(nltimes|rfi|le monde|prothom alo|edition\.mv|arab news|kossev|times of malta)\b",
    r"\b(nt police|delaware state police|hawaii police|portland police)\b",
    r"\b(survivors network of those abused by priests|football supporters' association|amazon web services|aws)\b",
    r"\b(san francisco chronicle|central nebraska today|spectrumlocalnews|clickondetroit|abc7news|wxyz|wtva|wtnh|wrgb|10tv|12news|6abc|9news)\b",
    r"\b(the icir|nigeria|nigerians|dc news now|kvue|katu|grice connect|13wham|collin county|ksbw|factly|new haven register|nonstop local|abc7 wwsb)\b",
    r"\b(fox\s*\d+|nbc\s*\d+|abc\s*\d+|cbs\s*\d+|news\s*\d+)\b",
    r"\b(applevalleynews|asianews\.network|the straits times)\b",
    r"\b(da\s+[a-z]+|district attorney|sheriff|county police|county jail)\b",
    r"\.gov\b|\.au\b|\.uk\b|\.ca\b|\.nz\b|\.za\b|\.nl\b|\.md\b|\.mv\b|\.edu\.au\b",
]

FOREIGN_GEOGRAPHY = [
    r"\b(britain|uk\b|u\.k\.|england|wales|scotland|london|nottingham|portsmouth|kent|essex|manchester|birmingham|glasgow|cardiff|belfast|sheffield|leeds)\b",
    r"\b(united states|u\.s\.|usa\b|texas|florida|california|ohio|massachusetts|kentucky|georgia|colorado|new york|new jersey|pennsylvania|virginia|arizona|michigan|illinois|chicago|houston|seattle|boston|washington dc|benton county|arkansas|suffolk county|costa mesa|indiana|oregon|minnesota|fresno|utah|pentagon|philadelphia|cleveland|maine|baltimore|alabama|connecticut|new orleans|nebraska|detroit|greenwood|huntington|athens-clarke|hyattsville|statesboro|yates county|carmel|marina|allen man|waterbury|san jose|las vegas|nevada|tennessee|missouri|oklahoma|wisconsin|iowa|kansas|louisiana|mississippi|idaho|montana|wyoming|rhode island|vermont|new hampshire|alaska|hawaii|nashville|memphis|knoxville|cincinnati|columbus|grand rapids|milwaukee|madison|st\. louis|kansas city|omaha|des moines|boise|spokane|tacoma|eugene|anchorage|honolulu|montgomery|mobile|huntsville|little rock|baton rouge|shreveport|jackson|tupelo|biloxi|san diego|san antonio|dallas|austin|fort worth|el paso|charlotte|raleigh|durham|jacksonville|miami|tampa|orlando|tallahassee|fort lauderdale|pembroke pines|gainesville|taylor frankie paul|dakota mortensen|mormon wives)\b",
    r"\b(australia|sydney|melbourne|brisbane|canberra|perth|adelaide|queensland|new south wales)\b",
    r"\b(france|paris|spain|ceuta|madrid|barcelona|italy|rome|germany|berlin|netherlands|amsterdam|belgium|portugal)\b",
    r"\b(pakistan|lahore|karachi|islamabad|bangladesh|dhaka|nepal|kathmandu|sri lanka|myanmar|cambodia|philippines|indonesia|bukidnon|blantyre)\b",
    r"\b(canada|toronto|vancouver|ottawa|montreal|ireland|galway|dublin|new zealand|auckland)\b",
    r"\b(romania|andrew tate|israel|gaza|hamas|ukraine|russia|china|japan|south korea|taiwan|brazil|argentina|mexico|jamaica|belize|south africa|johannesburg|cape town)\b",
]

FOREIGN_REGEX = re.compile("|".join(FOREIGN_OUTLETS_AND_DOMAINS + FOREIGN_GEOGRAPHY), re.IGNORECASE)

# ---------------------------------------------------------------------------
# 2. Strong Indian indicators (protect genuine Indian stories from false deletion)
# ---------------------------------------------------------------------------
INDIAN_MEDIA_AND_TERMS = [
    r"\b(india|indian|pocso|fir\b|ipc\b|bns\b|crpc|cji|thana|police station|mahila thana|panchayat|lakh|crore)\b",
    r"\b(the hindu|times of india|hindustan times|indian express|deccan herald|ndtv|the print|the wire|live law|livelaw|bar and bench|ani news|pti|india today|the tribune|deccan chronicle|the news minute|etv bharat|bhaskar english|rediff|moneycontrol|the quint|scroll\.in|mid-day|freepressjournal|the statesman|greater kashmir|kashmir life|millennium post|dt next)\b",
]
INDIAN_REGEX = re.compile("|".join(INDIAN_MEDIA_AND_TERMS), re.IGNORECASE)

# ---------------------------------------------------------------------------
# 3. Comprehensive Indian Localities & Prominent GBV Event Signatures
# ---------------------------------------------------------------------------
EVENT_AND_LOCALITY_MAPPINGS = [
    # Prominent national cases / signatures
    (re.compile(r"\b(moving bus|bus gang rape|bus on which girl was raped|route, just 2 barricades|bus rape)\b", re.I), "Delhi NCR", "Delhi NCR", "Delhi", 28.6139, 77.2090),
    (re.compile(r"\b(chambal bridge|chambal)\b", re.I), "Kota", "Kota", "Rajasthan", 25.2138, 75.8648),
    (re.compile(r"\b(msf constable|maharashtra security force)\b", re.I), "Mumbai", "Mumbai", "Maharashtra", 19.0760, 72.8777),
    (re.compile(r"\b(sandeshkhali)\b", re.I), "Sandeshkhali", "North 24 Parganas", "West Bengal", 22.3667, 88.8833),
    (re.compile(r"\b(rg kar|r\.g\. kar)\b", re.I), "Kolkata", "Kolkata", "West Bengal", 22.6033, 88.3754),
    (re.compile(r"\b(nirbhaya)\b", re.I), "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    (re.compile(r"\b(hathras)\b", re.I), "Hathras", "Hathras", "Uttar Pradesh", 27.5968, 78.0519),
    (re.compile(r"\b(unnao)\b", re.I), "Unnao", "Unnao", "Uttar Pradesh", 26.5492, 80.4878),
    (re.compile(r"\b(prajwal revanna|revanna)\b", re.I), "Hassan", "Hassan", "Karnataka", 13.0033, 76.1004),
    (re.compile(r"\b(ram rahim|dera sacha sauda)\b", re.I), "Sirsa", "Sirsa", "Haryana", 29.5300, 75.0300),
    (re.compile(r"\b(badlapur school|badlapur)\b", re.I), "Badlapur", "Thane", "Maharashtra", 19.1668, 73.2368),
    (re.compile(r"\b(kalka-shimla|shimla)\b", re.I), "Shimla", "Shimla", "Himachal Pradesh", 31.1048, 77.1734),
    (re.compile(r"\b(vrindavan)\b", re.I), "Vrindavan", "Mathura", "Uttar Pradesh", 27.5753, 77.6938),
    (re.compile(r"\b(ayodhya)\b", re.I), "Ayodhya", "Ayodhya", "Uttar Pradesh", 26.7922, 82.1998),
    (re.compile(r"\b(manipur)\b", re.I), "Imphal", "Imphal", "Manipur", 24.8170, 93.9368),
]

# Additional specific sub-districts and courts
SPECIFIC_PLACES = [
    (re.compile(r"\b(sirwar)\b", re.I), "Sirwar", "Raichur", "Karnataka", 16.0333, 77.0167),
    (re.compile(r"\b(bantwal)\b", re.I), "Bantwal", "Dakshina Kannada", "Karnataka", 12.8933, 75.0347),
    (re.compile(r"\b(dindoshi|dindoshi court)\b", re.I), "Dindoshi", "Mumbai Suburban", "Maharashtra", 19.1726, 72.8687),
    (re.compile(r"\b(sutia)\b", re.I), "Sutia", "North 24 Parganas", "West Bengal", 22.9800, 88.7500),
    (re.compile(r"\b(pimpalwandi)\b", re.I), "Pimpalwandi", "Pune", "Maharashtra", 19.1500, 74.0500),
    (re.compile(r"\b(chambal)\b", re.I), "Kota", "Kota", "Rajasthan", 25.2138, 75.8648),
    (re.compile(r"\b(kalyana k['’]?taka)\b", re.I), "Kalaburagi", "Kalaburagi", "Karnataka", 17.3297, 76.8343),
]

# Political leaders / CMs to state capital seat
LEADER_MAPPINGS = [
    (re.compile(r"\b(bhagwant mann|mann govt)\b", re.I), "Chandigarh", "Chandigarh", "Punjab", 30.7333, 76.7794),
    (re.compile(r"\b(yogi adityanath|yogi govt)\b", re.I), "Lucknow", "Lucknow", "Uttar Pradesh", 26.8467, 80.9462),
    (re.compile(r"\b(mamata banerjee|mamata|abhishek banerjee|tmc mla|tmc)\b", re.I), "Kolkata", "Kolkata", "West Bengal", 22.5726, 88.3639),
    (re.compile(r"\b(mk stalin|stalin govt|dmk|aiadmk)\b", re.I), "Chennai", "Chennai", "Tamil Nadu", 13.0827, 80.2707),
    (re.compile(r"\b(siddaramaiah|dk shivakumar|priyank kharge)\b", re.I), "Bengaluru", "Bengaluru", "Karnataka", 12.9716, 77.5946),
    (re.compile(r"\b(eknath shinde|devendra fadnavis|ajit pawar|sunetra pawar|sharad pawar)\b", re.I), "Mumbai", "Mumbai", "Maharashtra", 19.0760, 72.8777),
    (re.compile(r"\b(revanth reddy|kcr|brs)\b", re.I), "Hyderabad", "Hyderabad", "Telangana", 17.3850, 78.4867),
    (re.compile(r"\b(nitish kumar|tejashwi|rjd)\b", re.I), "Patna", "Patna", "Bihar", 25.0961, 85.3131),
    (re.compile(r"\b(hemant soren|jmm)\b", re.I), "Ranchi", "Ranchi", "Jharkhand", 23.6102, 85.2799),
    (re.compile(r"\b(himanta biswa sarma|himanta)\b", re.I), "Guwahati", "Guwahati", "Assam", 26.2006, 92.9376),
    (re.compile(r"\b(naveen patnaik|bjd)\b", re.I), "Bhubaneswar", "Bhubaneswar", "Odisha", 20.9517, 85.0985),
    (re.compile(r"\b(amit shah|pm modi|narendra modi|rajnath singh)\b", re.I), "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
]

# Non-GBV articles or foreign sources to purge
NON_GBV_OR_FOREIGN = [
    re.compile(r"\b(cureus|lifetime achievement award|signboard removal|scott kuggeleijn|hampshire withdraws|ms\. magazine)\b", re.I),
    re.compile(r"\b(applevalleynews|abc10|fox61|nbc los angeles|the straits times|nbc4 washington|13newsnow|newswest9|myupnow)\b", re.I),
    re.compile(r"\b(wpsd|wpta|fox59|wkyc|ksnv|wral|witn|gv wire|10tv|wjla|king5|6abc|12news|wsoc|wkyt|wcti|wciv)\b", re.I),
    re.compile(r"\b(central nebraska|san francisco chronicle|los angeles times|clickondetroit|abc7news|wxyz|wtva|wtnh|wrgb)\b", re.I),
    re.compile(r"\b(survivors network of those abused by priests|football supporters' association|amazon web services|aws)\b", re.I),
    re.compile(r"\b(vajiram & ravi|davisvanguard|localmemphis|local21news)\b", re.I),
    re.compile(r"\b(wbng|wsyx|live 5 news|korea joongang|ksla|joseph duggar|duggar)\b", re.I),
    re.compile(r"\b(mayor arrested|marion police officer|secret history of the rape kit)\b", re.I),
]

ADDITIONAL_PLACES = [
    (re.compile(r"\b(kodakara)\b", re.I), "Kodakara", "Thrissur", "Kerala", 10.3667, 76.3000),
    (re.compile(r"\b(palathayi)\b", re.I), "Palathayi", "Kannur", "Kerala", 11.7500, 75.5500),
    (re.compile(r"\b(keralam)\b", re.I), "Kerala", "Kerala", "Kerala", 10.8505, 76.2711),
    (re.compile(r"\b(rahul meena|irs['’]?s daughter)\b", re.I), "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    (re.compile(r"\b(abishek porel)\b", re.I), "Kolkata", "Kolkata", "West Bengal", 22.5726, 88.3639),
    (re.compile(r"\b(t logs|in t\b)\b", re.I), "Hyderabad", "Hyderabad", "Telangana", 17.3850, 78.4867),
    (re.compile(r"\b(prajwal)\b", re.I), "Hassan", "Hassan", "Karnataka", 13.0033, 76.1004),
    (re.compile(r"\b(veeramani)\b", re.I), "Chennai", "Chennai", "Tamil Nadu", 13.0827, 80.2707),
    (re.compile(r"\b(chiraiya)\b", re.I), "Chiraiya", "East Champaran", "Bihar", 26.5800, 85.0300),
    (re.compile(r"\b(thirumangalam)\b", re.I), "Thirumangalam", "Madurai", "Tamil Nadu", 9.8236, 77.9878),
    (re.compile(r"\b(maduranthakam)\b", re.I), "Maduranthakam", "Chengalpattu", "Tamil Nadu", 12.5097, 79.8847),
    (re.compile(r"\b(basar)\b", re.I), "Basar", "Leparada", "Arunachal Pradesh", 27.9800, 94.6700),
    (re.compile(r"\b(mallikarjun mutya)\b", re.I), "Kalaburagi", "Kalaburagi", "Karnataka", 17.3297, 76.8343),
    (re.compile(r"\b(shankaracharya)\b", re.I), "Varanasi", "Varanasi", "Uttar Pradesh", 25.3176, 82.9739),
]

REGIONAL_PUBLISHERS = [
    ("deshabhimani", "Thiruvananthapuram", "Thiruvananthapuram", "Kerala", 8.5241, 76.9366),
    ("dt next", "Chennai", "Chennai", "Tamil Nadu", 13.0827, 80.2707),
    ("the south first", "Chennai", "Chennai", "Tamil Nadu", 13.0827, 80.2707),
    ("arunachal times", "Itanagar", "Papum Pare", "Arunachal Pradesh", 27.0844, 93.6053),
    ("arunachal24", "Itanagar", "Papum Pare", "Arunachal Pradesh", 27.0844, 93.6053),
    ("greater kashmir", "Srinagar", "Srinagar", "Jammu and Kashmir", 34.0837, 74.7973),
    ("kashmir life", "Srinagar", "Srinagar", "Jammu and Kashmir", 34.0837, 74.7973),
    ("kashmir monitor", "Srinagar", "Srinagar", "Jammu and Kashmir", 34.0837, 74.7973),
    ("kashmir observer", "Srinagar", "Srinagar", "Jammu and Kashmir", 34.0837, 74.7973),
    ("kashmir reader", "Srinagar", "Srinagar", "Jammu and Kashmir", 34.0837, 74.7973),
    ("deccan chronicle", "Hyderabad", "Hyderabad", "Telangana", 17.3850, 78.4867),
    ("deccan herald", "Bengaluru", "Bengaluru", "Karnataka", 12.9716, 77.5946),
    ("the tribune", "Chandigarh", "Chandigarh", "Punjab", 30.7333, 76.7794),
    ("telegraph india", "Kolkata", "Kolkata", "West Bengal", 22.5726, 88.3639),
    ("millennium post", "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    ("millenniumpost", "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    ("daily pioneer", "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    ("the pioneer", "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
]

LOCALITIES = {
    # Delhi NCR
    "maujpur": ("Delhi", 28.6888, 77.2727),
    "ncr": ("Delhi", 28.6139, 77.2090),
    "delhi-ncr": ("Delhi", 28.6139, 77.2090),
    "dwarka": ("Delhi", 28.5921, 77.0460),
    "rohini": ("Delhi", 28.7495, 77.0565),
    "saket": ("Delhi", 28.5244, 77.2066),
    "vasant kunj": ("Delhi", 28.5292, 77.1539),
    "karol bagh": ("Delhi", 28.6517, 77.1906),
    "shahdara": ("Delhi", 28.6738, 77.2917),
    "laxmi nagar": ("Delhi", 28.6315, 77.2773),
    "mayur vihar": ("Delhi", 28.6080, 77.2974),
    "uttam nagar": ("Delhi", 28.6219, 77.0583),
    "janakpuri": ("Delhi", 28.6219, 77.0878),
    "pitampura": ("Delhi", 28.6990, 77.1384),
    "burari": ("Delhi", 28.7548, 77.1990),
    "seelampur": ("Delhi", 28.6698, 77.2677),
    "jamia": ("Delhi", 28.5616, 77.2802),
    "jnu": ("Delhi", 28.5400, 77.1666),
    "delhi university": ("Delhi", 28.6890, 77.2105),

    # Mumbai MMR
    "ghatkopar": ("Maharashtra", 19.0860, 72.9090),
    "bandra": ("Maharashtra", 19.0596, 72.8295),
    "andheri": ("Maharashtra", 19.1136, 72.8697),
    "borivali": ("Maharashtra", 19.2307, 72.8567),
    "dadar": ("Maharashtra", 19.0178, 72.8478),
    "worli": ("Maharashtra", 19.0134, 72.8150),
    "chembur": ("Maharashtra", 19.0622, 72.8973),
    "kurla": ("Maharashtra", 19.0657, 72.8794),
    "malad": ("Maharashtra", 19.1860, 72.8485),
    "kandivali": ("Maharashtra", 19.2062, 72.8526),
    "goregaon": ("Maharashtra", 19.1663, 72.8526),
    "powai": ("Maharashtra", 19.1176, 72.9060),
    "juhu": ("Maharashtra", 19.0988, 72.8264),
    "colaba": ("Maharashtra", 18.9067, 72.8147),
    "bhayandar": ("Maharashtra", 19.2952, 72.8544),
    "mira road": ("Maharashtra", 19.2812, 72.8561),
    "badlapur": ("Maharashtra", 19.1668, 73.2368),
    "ulhasnagar": ("Maharashtra", 19.2215, 73.1645),
    "kalyan": ("Maharashtra", 19.2437, 73.1355),
    "dombivli": ("Maharashtra", 19.2184, 73.0867),

    # Kolkata
    "salt lake": ("West Bengal", 22.5867, 88.4178),
    "new town": ("West Bengal", 22.5937, 88.4820),
    "park street": ("West Bengal", 22.5519, 88.3524),
    "jadavpur": ("West Bengal", 22.4990, 88.3716),
    "alipore": ("West Bengal", 22.5312, 88.3287),
    "dum dum": ("West Bengal", 22.6420, 88.4312),
    "garfa": ("West Bengal", 22.5001, 88.3756),
    "baruipur": ("West Bengal", 22.3607, 88.4326),
    "phansidewa": ("West Bengal", 26.5753, 88.2985),

    # Bengaluru
    "whitefield": ("Karnataka", 12.9698, 77.7500),
    "koramangala": ("Karnataka", 12.9352, 77.6245),
    "indiranagar": ("Karnataka", 12.9784, 77.6408),
    "jayanagar": ("Karnataka", 12.9308, 77.5838),
    "electronic city": ("Karnataka", 12.8452, 77.6602),
    "hebbal": ("Karnataka", 13.0358, 77.5970),
    "marathahalli": ("Karnataka", 12.9591, 77.6974),

    # Chennai
    "t nagar": ("Tamil Nadu", 13.0418, 80.2341),
    "velachery": ("Tamil Nadu", 12.9759, 80.2212),
    "adyar": ("Tamil Nadu", 13.0012, 80.2565),
    "anna nagar": ("Tamil Nadu", 13.0850, 80.2101),
    "tambaram": ("Tamil Nadu", 12.9249, 80.1000),

    # Hyderabad
    "secunderabad": ("Telangana", 17.4399, 78.4983),
    "gachibowli": ("Telangana", 17.4401, 78.3489),
    "hitec city": ("Telangana", 17.4474, 78.3762),
    "banjara hills": ("Telangana", 17.4156, 78.4357),
    "jubilee hills": ("Telangana", 17.4319, 78.4073),
    "cyberabad": ("Telangana", 17.4401, 78.3489),
    "rachakonda": ("Telangana", 17.3600, 78.5500),
    "kukkatpally": ("Telangana", 17.4849, 78.4138),
}

LOCALITY_REGEX = re.compile(r"\b(" + "|".join(re.escape(loc) for loc in sorted(LOCALITIES.keys(), key=len, reverse=True)) + r")\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# 4. State Police Force attribution
# ---------------------------------------------------------------------------
POLICE_MAPPINGS = [
    (re.compile(r"\b(delhi police)\b", re.I), "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    (re.compile(r"\b(mumbai police)\b", re.I), "Mumbai", "Mumbai", "Maharashtra", 19.0760, 72.8777),
    (re.compile(r"\b(kolkata police)\b", re.I), "Kolkata", "Kolkata", "West Bengal", 22.5726, 88.3639),
    (re.compile(r"\b(bengaluru police|bangalore police)\b", re.I), "Bengaluru", "Bengaluru", "Karnataka", 12.9716, 77.5946),
    (re.compile(r"\b(hyderabad police)\b", re.I), "Hyderabad", "Hyderabad", "Telangana", 17.3850, 78.4867),
    (re.compile(r"\b(chennai police)\b", re.I), "Chennai", "Chennai", "Tamil Nadu", 13.0827, 80.2707),
    (re.compile(r"\b(up police|uttar pradesh police)\b", re.I), "Lucknow", "Lucknow", "Uttar Pradesh", 26.8467, 80.9462),
    (re.compile(r"\b(kerala police)\b", re.I), "Thiruvananthapuram", "Thiruvananthapuram", "Kerala", 10.8505, 76.2711),
    (re.compile(r"\b(bihar police)\b", re.I), "Patna", "Patna", "Bihar", 25.0961, 85.3131),
    (re.compile(r"\b(punjab police)\b", re.I), "Chandigarh", "Chandigarh", "Punjab", 31.1471, 75.3412),
    (re.compile(r"\b(haryana police)\b", re.I), "Panchkula", "Panchkula", "Haryana", 29.0588, 76.0856),
    (re.compile(r"\b(rajasthan police)\b", re.I), "Jaipur", "Jaipur", "Rajasthan", 27.0238, 74.2179),
    (re.compile(r"\b(mp police|madhya pradesh police)\b", re.I), "Bhopal", "Bhopal", "Madhya Pradesh", 22.9734, 78.6569),
    (re.compile(r"\b(gujarat police)\b", re.I), "Gandhinagar", "Gandhinagar", "Gujarat", 22.2587, 71.1924),
    (re.compile(r"\b(assam police)\b", re.I), "Guwahati", "Guwahati", "Assam", 26.2006, 92.9376),
    (re.compile(r"\b(odisha police)\b", re.I), "Bhubaneswar", "Bhubaneswar", "Odisha", 20.9517, 85.0985),
    (re.compile(r"\b(jharkhand police)\b", re.I), "Ranchi", "Ranchi", "Jharkhand", 23.6102, 85.2799),
    (re.compile(r"\b(chhattisgarh police)\b", re.I), "Raipur", "Raipur", "Chhattisgarh", 21.2787, 81.8661),
    (re.compile(r"\b(uttarakhand police)\b", re.I), "Dehradun", "Dehradun", "Uttarakhand", 30.0668, 79.0193),
    (re.compile(r"\b(himachal police)\b", re.I), "Shimla", "Shimla", "Himachal Pradesh", 31.1048, 77.1734),
    (re.compile(r"\b(goa police)\b", re.I), "Panaji", "Panaji", "Goa", 15.2993, 74.1240),
]

# ---------------------------------------------------------------------------
# 5. Judicial & Legal Jurisdiction attribution
# ---------------------------------------------------------------------------
JUDICIAL_MAPPINGS = [
    (re.compile(r"\b(sc|supreme court|apex court|cji|plea in sc|sc notice)\b", re.I), "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    (re.compile(r"\b(delhi hc|delhi high court)\b", re.I), "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    (re.compile(r"\b(bombay hc|bombay high court)\b", re.I), "Mumbai", "Mumbai", "Maharashtra", 18.9220, 72.8347),
    (re.compile(r"\b(calcutta hc|calcutta high court)\b", re.I), "Kolkata", "Kolkata", "West Bengal", 22.5697, 88.3697),
    (re.compile(r"\b(madras hc|madras high court)\b", re.I), "Chennai", "Chennai", "Tamil Nadu", 13.0827, 80.2707),
    (re.compile(r"\b(karnataka hc|karnataka high court)\b", re.I), "Bengaluru", "Bengaluru", "Karnataka", 12.9716, 77.5946),
    (re.compile(r"\b(allahabad hc|allahabad high court)\b", re.I), "Prayagraj", "Prayagraj", "Uttar Pradesh", 25.4358, 81.8463),
    (re.compile(r"\b(kerala hc|kerala high court)\b", re.I), "Kochi", "Ernakulam", "Kerala", 9.9312, 76.2673),
    (re.compile(r"\b(patna hc|patna high court)\b", re.I), "Patna", "Patna", "Bihar", 25.5941, 85.1376),
    (re.compile(r"\b(punjab and haryana hc|punjab & haryana hc|punjab and haryana high court)\b", re.I), "Chandigarh", "Chandigarh", "Punjab", 30.7333, 76.7794),
    (re.compile(r"\b(rajasthan hc|rajasthan high court)\b", re.I), "Jodhpur", "Jodhpur", "Rajasthan", 26.2389, 73.0243),
    (re.compile(r"\b(gujarat hc|gujarat high court)\b", re.I), "Ahmedabad", "Ahmedabad", "Gujarat", 23.0225, 72.5714),
    (re.compile(r"\b(gauhati hc|gauhati high court)\b", re.I), "Guwahati", "Guwahati", "Assam", 26.1445, 91.7362),
    (re.compile(r"\b(telangana hc|telangana high court)\b", re.I), "Hyderabad", "Hyderabad", "Telangana", 17.3850, 78.4867),
    (re.compile(r"\b(high court|hc grants|hc rejects|hc asks|hc quashes|hc upholds|hc stays)\b", re.I), "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
    (re.compile(r"\b(live law|livelaw|bar and bench|scc online|verdictum)\b", re.I), "New Delhi", "New Delhi", "Delhi", 28.6139, 77.2090),
]

# ---------------------------------------------------------------------------
# 6. State Adjective indicators
# ---------------------------------------------------------------------------
STATE_ADJECTIVES = [
    (re.compile(r"\b(up|u\.p\.)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Uttar Pradesh", 26.8467, 80.9462),
    (re.compile(r"\b(mp|m\.p\.)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Madhya Pradesh", 22.9734, 78.6569),
    (re.compile(r"\b(bengal|wb)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "West Bengal", 22.9868, 87.8550),
    (re.compile(r"\b(kerala)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Kerala", 10.8505, 76.2711),
    (re.compile(r"\b(bihar)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Bihar", 25.0961, 85.3131),
    (re.compile(r"\b(punjab)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Punjab", 31.1471, 75.3412),
    (re.compile(r"\b(haryana)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Haryana", 29.0588, 76.0856),
    (re.compile(r"\b(rajasthan)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Rajasthan", 27.0238, 74.2179),
    (re.compile(r"\b(gujarat)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Gujarat", 22.2587, 71.1924),
    (re.compile(r"\b(odisha)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Odisha", 20.9517, 85.0985),
    (re.compile(r"\b(assam)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Assam", 26.2006, 92.9376),
    (re.compile(r"\b(kashmir)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Jammu and Kashmir", 33.7782, 76.5762),
    (re.compile(r"\b(delhi)\s+(man|woman|girl|teen|boy|victim|cop|police|accused|family|youth|minor|student|resident)\b", re.I), "Delhi", 28.7041, 77.1025),
    (re.compile(r"\b(centre|rahul gandhi|bjp mla|aap)\b", re.I), "New Delhi", 28.6139, 77.2090),
]

def clean_html_summary(text: str) -> str:
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

def run_remediation():
    print("=" * 65)
    print("GBV Explorer: High-Accuracy Geocoding & Foreign Report Cleanup")
    print("=" * 65)

    gaz = load_gazetteer()
    places = gaz.get("places", {})
    states = gaz.get("states", {})

    # Build compiled places regex (all valid 4+ char place names)
    valid_places = [p for p in places.keys() if len(p) >= 4]
    valid_places.sort(key=len, reverse=True)
    PLACE_REGEX = re.compile(r"\b(" + "|".join(re.escape(p) for p in valid_places) + r")\b", re.IGNORECASE)

    valid_states = sorted(states.keys(), key=len, reverse=True)
    STATE_REGEX = re.compile(r"\b(" + "|".join(re.escape(s) for s in valid_states) + r")\b", re.IGNORECASE)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as total FROM incidents")
    initial_total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as geo FROM incidents WHERE latitude IS NOT NULL")
    initial_geo = cur.fetchone()["geo"]

    print(f"Initial DB State: {initial_total} total incidents ({initial_geo} geocoded = {initial_geo/initial_total*100:.1f}%)")

    # Fetch all ungeocoded incidents
    cur.execute("""
        SELECT i.id, i.title, i.summary, s.headline, s.publisher, s.url, s.raw_snippet
        FROM incidents i
        LEFT JOIN sources s ON s.incident_id = i.id
        WHERE i.latitude IS NULL OR i.longitude IS NULL
    """)
    rows = cur.fetchall()
    print(f"Ungeocoded incidents to process: {len(rows)}\n")

    deleted_foreign = 0
    resolved_count = 0
    clean_summary_count = 0

    to_delete = []
    to_update = []

    for r in rows:
        inc_id = r["id"]
        stored_summary = r["summary"] or ""
        clean_sum = clean_html_summary(stored_summary)
        if stored_summary != clean_sum and len(clean_sum) > 5:
            cur.execute("UPDATE incidents SET summary = ? WHERE id = ?", (clean_sum[:500], inc_id))
            clean_summary_count += 1

        title = r["title"] or ""
        headline = r["headline"] or ""
        publisher = r["publisher"] or ""
        url = r["url"] or ""
        raw_snippet = clean_html_summary(r["raw_snippet"] or "")

        full_text = f"{title}. {clean_sum}. {headline}. {publisher}. {raw_snippet}. {url}"

        # 1. Non-GBV or Foreign Check
        if any(p.search(full_text) for p in NON_GBV_OR_FOREIGN):
            to_delete.append(inc_id)
            deleted_foreign += 1
            continue

        # 1b. Foreign Classification Check
        has_india = bool(INDIAN_REGEX.search(full_text))
        is_foreign = bool(FOREIGN_REGEX.search(full_text))

        if is_foreign and not has_india:
            to_delete.append(inc_id)
            deleted_foreign += 1
            continue

        # 2. National GBV Event & High-Profile Signature Check
        event_found = False
        for pat, loc, dist, st, lat, lon in EVENT_AND_LOCALITY_MAPPINGS:
            if pat.search(full_text):
                to_update.append((loc, dist, st, lat, lon, inc_id))
                resolved_count += 1
                event_found = True
                break
        if event_found:
            continue

        # 2b. Specific Sub-districts & Courts
        spec_found = False
        for pat, loc, dist, st, lat, lon in SPECIFIC_PLACES:
            if pat.search(full_text):
                to_update.append((loc, dist, st, lat, lon, inc_id))
                resolved_count += 1
                spec_found = True
                break
        if spec_found:
            continue

        # 2c. Political Leaders & CMs
        lead_found = False
        for pat, loc, dist, st, lat, lon in LEADER_MAPPINGS:
            if pat.search(full_text):
                to_update.append((loc, dist, st, lat, lon, inc_id))
                resolved_count += 1
                lead_found = True
                break
        if lead_found:
            continue

        # 3. Localities
        m = LOCALITY_REGEX.search(full_text)
        if m:
            loc = m.group(1).lower()
            state, lat, lon = LOCALITIES[loc]
            to_update.append((loc.title(), loc.title(), state, lat, lon, inc_id))
            resolved_count += 1
            continue

        # 4. Places from Gazetteer (includes 4-letter names like Pune, Agra, Gaya, Kota)
        m = PLACE_REGEX.search(full_text)
        if m:
            p = m.group(1).lower()
            info = places[p]
            to_update.append((p.title(), p.title(), info.get("state"), info["lat"], info["lon"], inc_id))
            resolved_count += 1
            continue

        # 5. State Police
        police_found = False
        for pat, loc, dist, st, lat, lon in POLICE_MAPPINGS:
            if pat.search(full_text):
                to_update.append((loc, dist, st, lat, lon, inc_id))
                resolved_count += 1
                police_found = True
                break
        if police_found:
            continue

        # 6. State Adjectives
        adj_found = False
        for pat, st, lat, lon in STATE_ADJECTIVES:
            if pat.search(full_text):
                to_update.append((st, st, st, lat, lon, inc_id))
                resolved_count += 1
                adj_found = True
                break
        if adj_found:
            continue

        # 7. Judicial Jurisdiction
        jud_found = False
        for pat, loc, dist, st, lat, lon in JUDICIAL_MAPPINGS:
            if pat.search(full_text):
                to_update.append((loc, dist, st, lat, lon, inc_id))
                resolved_count += 1
                jud_found = True
                break
        if jud_found:
            continue

        # 8. States
        m = STATE_REGEX.search(full_text)
        if m:
            s = m.group(1).title()
            if s in states:
                info = states[s]
                to_update.append((s, s, s, info["lat"], info["lon"], inc_id))
                resolved_count += 1
                continue

        # 9. Additional high-profile places
        add_found = False
        for pat, loc, dist, st, lat, lon in ADDITIONAL_PLACES:
            if pat.search(full_text):
                to_update.append((loc, dist, st, lat, lon, inc_id))
                resolved_count += 1
                add_found = True
                break
        if add_found:
            continue

        # 10. Regional Newspaper attribution (for domestic state reports)
        pub_lower = publisher.lower()
        rpub_found = False
        for rpub, loc, dist, st, lat, lon in REGIONAL_PUBLISHERS:
            if rpub in pub_lower:
                to_update.append((loc, dist, st, lat, lon, inc_id))
                resolved_count += 1
                rpub_found = True
                break
        if rpub_found:
            continue

    # Execute DB updates in batch
    print(f"Applying changes:")
    print(f"  - Deleting {len(to_delete)} foreign reports...")
    for inc_id in to_delete:
        cur.execute("DELETE FROM sources WHERE incident_id = ?", (inc_id,))
        cur.execute("DELETE FROM incidents WHERE id = ?", (inc_id,))

    print(f"  - Geocoding {len(to_update)} Indian reports...")
    cur.executemany("""
        UPDATE incidents
        SET location_name=?, district=?, state=?, latitude=?, longitude=?
        WHERE id=?
    """, to_update)

    conn.commit()

    cur.execute("SELECT COUNT(*) as total FROM incidents")
    final_total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as geo FROM incidents WHERE latitude IS NOT NULL")
    final_geo = cur.fetchone()["geo"]
    conn.close()

    print("\n" + "=" * 65)
    print("Remediation Summary:")
    print(f"  Deleted Foreign/Non-India Reports: {deleted_foreign}")
    print(f"  Newly Geocoded Domestic Incidents: {resolved_count}")
    print(f"  Summaries Cleaned:                 {clean_summary_count}")
    print(f"\nFinal Database State:")
    print(f"  Total Incidents:    {final_total}")
    print(f"  Geocoded Incidents: {final_geo} ({final_geo/final_total*100:.1f}%)")
    print("=" * 65)

    print("\nExporting fresh static datasets for Web & GitHub Pages...")
    export_static_data()
    print("[Success] Re-geocoding, cleanup, and static deployment sync complete!")

if __name__ == "__main__":
    run_remediation()
