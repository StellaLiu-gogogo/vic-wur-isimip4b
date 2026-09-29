"""ISO3 -> analysis region mapping for the ISIMIP fractional country masks (248 codes, version 2026.07i).

Regions are country groups (not strict continents) chosen to separate the major irrigation regions.
Every ISO3 present in countrymasks-fractional_15arcmin.nc must be mapped; the script checks this.
"""

REGION_ORDER = [
    "North America", "Central America & Caribbean", "South America",
    "Europe", "Russia", "Middle East & North Africa", "Sub-Saharan Africa",
    "Central Asia", "South Asia", "East Asia", "Southeast Asia", "Oceania",
]

_R = {
    "North America": "CAN USA GRL SPM BMU",
    "Central America & Caribbean": ("MEX BLZ GTM HND SLV NIC CRI PAN CUB HTI DOM JAM PRI BHS TTO BRB ABW AIA ATG BES BLM "
                                    "CUW CYM DMA GLP GRD KNA LCA MAF MSR MTQ SXM TCA VCT VGB VIR"),
    "South America": "BRA ARG CHL PER COL VEN ECU BOL PRY URY GUY SUR GUF FLK SGS BVT",
    "Europe": ("ALB AND AUT BEL BGR BIH BLR CHE CYP CZE DEU DNK ESP EST FIN FRA FRO GBR GGY GIB GRC HRV HUN IMN IRL ISL "
               "ITA JEY LIE LTU LUX LVA MCO MDA MKD MLT MNE NLD NOR POL PRT ROU SJM SMR SRB SVK SVN SWE UKR VAT XKX"),
    "Russia": "RUS",
    "Middle East & North Africa": ("TUR IRN IRQ SYR LBN ISR PSE JOR SAU YEM OMN ARE QAT BHR KWT EGY LBY TUN DZA MAR ESH "
                                   "GEO ARM AZE"),
    "Sub-Saharan Africa": ("AGO BDI BEN BFA BWA CAF CIV CMR COD COG COM CPV DJI ERI ETH GAB GHA GIN GMB GNB GNQ KEN LBR "
                           "LSO MDG MLI MOZ MRT MUS MWI MYT NAM NER NGA REU RWA SDN SEN SHN SLE SOM SSD STP SWZ SYC TCD "
                           "TGO TZA UGA ZAF ZMB ZWE ATF IOT"),
    "Central Asia": "KAZ UZB TKM KGZ TJK",
    "South Asia": "IND PAK BGD NPL BTN LKA MDV AFG",
    "East Asia": "CHN TWN HKG MAC JPN KOR PRK MNG",
    "Southeast Asia": "IDN MYS THA VNM PHL MMR KHM LAO SGP BRN TLS",
    "Oceania": ("AUS NZL PNG FJI SLB VUT NCL PYF WSM ASM TON KIR FSM MHL PLW NRU TUV NIU COK TKL WLF GUM MNP NFK PCN "
                "CXR CCK UMI HMD"),
}

ISO3_TO_REGION = {}
for _reg, _codes in _R.items():
    for _c in _codes.split():
        assert _c not in ISO3_TO_REGION, _c
        ISO3_TO_REGION[_c] = _reg
