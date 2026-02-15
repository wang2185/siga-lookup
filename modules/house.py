"""개별주택가격 조회 — V-World API."""

import requests

from .base import BaseLookupModule, LookupResult

API_URL = "https://api.vworld.kr/ned/data/getIndvdHousingPriceAttr"


class HousePriceModule(BaseLookupModule):

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    @property
    def property_type(self) -> str:
        return "house"

    @property
    def property_type_label(self) -> str:
        return "개별주택 (개별주택가격)"

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
        stdr_year = year or str(datetime.now().year - 1)

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

            # V-World NED API 응답 구조 호환 처리
            container = data.get("indvdHousingPrices", {})
            if not container and "response" in data:
                container_fields = data["response"].get("fields", {})
                container = {"field": container_fields.get("indvdHousingPrices", [])}
            items = container.get("field", [])
            if not isinstance(items, list):
                items = [items] if items else []

            results = []
            for item in items:
                # V-World NED 실제 필드명 우선, data.go.kr 호환 필드명 폴백
                price = (item.get("housePc", "")
                         or item.get("pblntfPc", ""))
                land_area = (item.get("calcPlotAr", "")
                             or item.get("ldAr", ""))
                building_area = (item.get("buldCalcTotAr", "")
                                 or item.get("bldgAr", ""))
                results.append({
                    "year": item.get("stdrYear", ""),
                    "price": price,
                    "land_area": land_area,
                    "building_area": building_area,
                    "location": item.get("ldCodeNm", ""),
                    "lot_number": item.get("mnnmSlno", ""),
                    "announcement_date": item.get("pblntfDe", ""),
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
