"""
Version Debt & CDNJS Release History Calculator.
Calculates exact release age, major version gap, and End-of-Life (EOL) status
for detected frontend and CMS libraries (jQuery, AngularJS, Bootstrap, Vue, React, WordPress).
"""

from dataclasses import dataclass, asdict
from datetime import datetime
import re
from typing import Any


@dataclass
class LibraryVersionInfo:
    library_name: str
    detected_version: str
    latest_stable_version: str
    release_year: int
    years_outdated: float
    major_versions_behind: int
    is_eol: bool
    cve_risk_level: str  # 'critical', 'high', 'medium', 'low'
    summary: str


# CDNJS / Official Release History Registry for Top Frontend & CMS Stacks
LIBRARY_CATALOG: dict[str, dict[str, Any]] = {
    "jquery": {
        "latest": "3.7.1",
        "latest_year": 2023,
        "versions": {
            "1.0": 2006, "1.1": 2007, "1.2": 2007, "1.3": 2009, "1.4": 2010,
            "1.5": 2011, "1.6": 2011, "1.7": 2011, "1.8": 2012, "1.9": 2013,
            "1.10": 2013, "1.11": 2014, "1.12": 2016,
            "2.0": 2013, "2.1": 2014, "2.2": 2016,
            "3.0": 2016, "3.1": 2016, "3.2": 2017, "3.3": 2018, "3.4": 2019,
            "3.5": 2020, "3.6": 2021, "3.7": 2023,
        },
        "eol_before": "3.0.0",
    },
    "angularjs": {
        "latest": "1.8.3",
        "latest_year": 2022,
        "versions": {
            "1.0": 2012, "1.1": 2013, "1.2": 2013, "1.3": 2014, "1.4": 2015,
            "1.5": 2016, "1.6": 2016, "1.7": 2018, "1.8": 2020,
        },
        "eol_before": "99.0.0",  # All AngularJS 1.x is officially EOL as of Jan 2022
    },
    "bootstrap": {
        "latest": "5.3.3",
        "latest_year": 2024,
        "versions": {
            "2.0": 2012, "2.3": 2013,
            "3.0": 2013, "3.3": 2014, "3.4": 2019,
            "4.0": 2018, "4.3": 2019, "4.5": 2020, "4.6": 2021,
            "5.0": 2021, "5.1": 2021, "5.2": 2022, "5.3": 2023,
        },
        "eol_before": "5.0.0",
    },
    "vue": {
        "latest": "3.4.0",
        "latest_year": 2024,
        "versions": {
            "1.0": 2015, "2.0": 2016, "2.5": 2017, "2.6": 2019, "2.7": 2022,
            "3.0": 2020, "3.2": 2021, "3.3": 2023, "3.4": 2024,
        },
        "eol_before": "3.0.0",  # Vue 2 reached EOL on Dec 31, 2023
    },
    "react": {
        "latest": "18.3.1",
        "latest_year": 2024,
        "versions": {
            "0.14": 2015, "15.0": 2016, "15.6": 2017,
            "16.0": 2017, "16.8": 2019, "17.0": 2020, "18.0": 2022,
        },
        "eol_before": "16.8.0",  # Pre-hooks React
    },
    "wordpress": {
        "latest": "6.7.1",
        "latest_year": 2024,
        "versions": {
            "3.0": 2010, "4.0": 2014, "4.9": 2017,
            "5.0": 2018, "5.5": 2020, "5.8": 2021, "5.9": 2022,
            "6.0": 2022, "6.1": 2022, "6.2": 2023, "6.3": 2023,
            "6.4": 2023, "6.5": 2024, "6.6": 2024, "6.7": 2024,
        },
        "eol_before": "6.0.0",
    },
}


class VersionDebtCalculator:
    """Calculates age debt, major version gaps, and security risks for detected software."""

    def __init__(self, current_year: int | None = None):
        self.current_year = current_year or datetime.now().year

    def calculate(self, library: str, version_str: str | None) -> LibraryVersionInfo | None:
        lib_key = library.lower().strip()
        if lib_key not in LIBRARY_CATALOG or not version_str:
            return None

        cat = LIBRARY_CATALOG[lib_key]
        latest_version = cat["latest"]
        latest_major = int(latest_version.split(".")[0])

        # Parse detected version
        clean_v = re.sub(r"[^\d.]", "", version_str).strip(".")
        if not clean_v:
            return None

        v_parts = clean_v.split(".")
        try:
            detected_major = int(v_parts[0])
            detected_minor = int(v_parts[1]) if len(v_parts) > 1 else 0
        except (ValueError, IndexError):
            return None

        major_gap = max(0, latest_major - detected_major)

        # Estimate release year
        key_2 = f"{detected_major}.{detected_minor}"
        key_1 = f"{detected_major}.0"
        release_year = cat["versions"].get(key_2) or cat["versions"].get(key_1)

        if not release_year:
            # Fallback estimation based on major version
            if detected_major == latest_major:
                release_year = cat["latest_year"] - 1
            else:
                release_year = 2015

        years_outdated = max(0.0, float(self.current_year - release_year))

        # Check EOL status
        eol_threshold = cat.get("eol_before", "0.0.0")
        eol_major = int(eol_threshold.split(".")[0])
        is_eol = (detected_major < eol_major) or (lib_key == "angularjs")

        # Determine CVE Risk Level
        if is_eol or years_outdated >= 8 or major_gap >= 2:
            cve_risk = "critical"
        elif (years_outdated >= 5 and major_gap >= 1) or major_gap >= 1:
            cve_risk = "high"
        elif years_outdated >= 4:
            cve_risk = "medium"
        else:
            cve_risk = "low"

        # Summary pitch copy
        if is_eol:
            summary = (
                f"{library.title()} v{version_str} is officially End-of-Life (released ~{release_year}, "
                f"{years_outdated:.0f} yrs ago). {major_gap} major version(s) behind current v{latest_version}."
            )
        elif years_outdated >= 3:
            summary = (
                f"{library.title()} v{version_str} is {years_outdated:.0f} years outdated (~{release_year}), "
                f"{major_gap} major version(s) behind latest stable v{latest_version}."
            )
        else:
            summary = f"{library.title()} v{version_str} is reasonably modern (latest v{latest_version})."

        return LibraryVersionInfo(
            library_name=library,
            detected_version=version_str,
            latest_stable_version=latest_version,
            release_year=release_year,
            years_outdated=years_outdated,
            major_versions_behind=major_gap,
            is_eol=is_eol,
            cve_risk_level=cve_risk,
            summary=summary,
        )


def calculate_tech_debt(library: str, version_str: str | None) -> dict[str, Any] | None:
    calc = VersionDebtCalculator()
    info = calc.calculate(library, version_str)
    return asdict(info) if info else None
