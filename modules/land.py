"""토지 개별공시지가 조회 — V-World API."""

import requests

from .base import BaseLookupModule, LookupResult

API_URL = "https://api.vworld.kr/ned/data/getIndvdLandPriceAttr"
LAND_MOVE_API_URL = "https://api.vworld.kr/ned/data/getLandMoveAttr"


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

    def _fetch_land_area(self, pnu: str, stdr_year: str) -> str:
        """getLandMoveAttr API로 토지 면적(lndpclAr)을 조회한다."""
        try:
            params = {
                "key": self.api_key,
                "pnu": pnu,
                "stdrYear": stdr_year,
                "format": "json",
                "numOfRows": 1,
                "pageNo": 1,
            }
            resp = requests.get(LAND_MOVE_API_URL, params=params, timeout=10)
            data = resp.json()
            container = data.get("landMoves", {})
            items = container.get("field", [])
            if not isinstance(items, list):
                items = [items] if items else []
            if items:
                return items[0].get("lndpclAr", "")
        except Exception:
            pass
        return ""

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
            container = data.get("indvdLandPrices", {})
            if not container and "response" in data:
                container_fields = data["response"].get("fields", {})
                container = {"field": container_fields.get("indvdLandPrices", [])}
            items = container.get("field", [])
            if not isinstance(items, list):
                items = [items] if items else []

            results = []
            for item in items:
                price_per_sqm = item.get("pblntfPclnd", "")
                land_area = item.get("lndpclAr", "") or item.get("ldAr", "")
                item_pnu = item.get("pnu", "")

                # 면적이 없으면 getLandMoveAttr API로 보충 조회
                if not land_area and item_pnu:
                    land_area = self._fetch_land_area(
                        item_pnu, item.get("stdrYear", stdr_year)
                    )

                total_price = ""
                if price_per_sqm and land_area:
                    try:
                        total_price = str(int(float(price_per_sqm) * float(land_area)))
                    except (ValueError, TypeError):
                        pass
                results.append({
                    "pnu": item_pnu,
                    "year": item.get("stdrYear", ""),
                    "price_per_sqm": price_per_sqm,
                    "land_area": land_area,
                    "total_price": total_price,
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
