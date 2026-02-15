"""토지 개별공시지가 조회 — V-World API."""

import requests

from .base import BaseLookupModule, LookupResult

API_URL = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"


class LandPriceModule(BaseLookupModule):

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def property_type(self) -> str:
        return "land"

    @property
    def property_type_label(self) -> str:
        return "토지 (개별공시지가)"

    @property
    def source_name(self) -> str:
        return "V-World"

    def search(self, address: dict, year: str = "", **kwargs) -> LookupResult:
        if not self.api_key:
            return LookupResult(
                success=False, property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""), year=year,
                source=self.source_name,
                error="V-World API 키가 설정되지 않았습니다.",
            )

        pnu = address.get("pnu", "")
        adm_cd = address.get("adm_cd", "")

        # PNU가 없으면 법정동코드(10자리)로 시도
        search_pnu = pnu or adm_cd
        if not search_pnu:
            return LookupResult(
                success=False, property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""), year=year,
                source=self.source_name,
                error="PNU 또는 법정동코드를 추출할 수 없습니다. 주소를 자동완성에서 선택해주세요.",
            )

        from datetime import datetime
        stdr_year = year or str(datetime.now().year)

        try:
            params = {
                "key": self.api_key,
                "pnu": search_pnu,
                "stdrYear": stdr_year,
                "format": "json",
                "numOfRows": 50,
                "pageNo": 1,
            }
            resp = requests.get(API_URL, params=params, timeout=15)
            data = resp.json()

            items = (data.get("indvdLandPrices", {})
                        .get("field", []))
            if not isinstance(items, list):
                items = [items] if items else []

            results = []
            for item in items:
                results.append({
                    "pnu": item.get("pnu", ""),
                    "year": item.get("stdrYear", ""),
                    "price_per_sqm": item.get("pblntfPclnd", ""),
                    "announcement_date": item.get("pblntfDe", ""),
                    "location": item.get("ldCodeNm", ""),
                    "lot_number": item.get("mnnmSlno", ""),
                    "lot_type": item.get("regstrSeCodeNm", ""),
                    "standard_land": item.get("stdLandAt", ""),
                })

            return LookupResult(
                success=True, property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""), year=stdr_year,
                results=results, source=self.source_name,
            )

        except Exception as e:
            return LookupResult(
                success=False, property_type=self.property_type,
                property_type_label=self.property_type_label,
                address=address.get("_raw", ""), year=stdr_year,
                source=self.source_name,
                error=f"API 조회 오류: {e}",
            )
