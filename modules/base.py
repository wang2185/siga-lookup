"""조회 모듈 공통 인터페이스."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LookupResult:
    success: bool
    property_type: str              # "land", "apartment", "house", "building", "commercial", "factory"
    property_type_label: str        # "토지", "공동주택" 등
    address: str
    year: str
    results: list[dict] = field(default_factory=list)
    source: str = ""                # "data.go.kr", "wetax", "etax", "hometax"
    error: Optional[str] = None
    message: Optional[str] = None
    logs: list[str] = field(default_factory=list)
    cached: bool = False


PROPERTY_TYPES = {
    "land":       "토지 (개별공시지가)",
    "apartment":  "공동주택 (공동주택가격)",
    "house":      "개별주택 (개별주택가격)",
    "building":   "주택외건물 (시가표준액)",
    "commercial": "상가/오피스텔 (기준시가)",
    "factory":    "공장 (시가표준액)",
}


# 법원 제출용 출처 상세 정보
SOURCE_INFO = {
    "land": {
        "name": "개별공시지가",
        "authority": "국토교통부",
        "provider": "한국부동산원",
        "system": "V-World 공간정보 오픈플랫폼 (vworld.kr)",
        "law": "부동산 가격공시에 관한 법률 제10조",
        "url": "https://www.realtyprice.kr",
    },
    "apartment": {
        "name": "공동주택 공시가격",
        "authority": "국토교통부",
        "provider": "한국부동산원",
        "system": "V-World 공간정보 오픈플랫폼 (vworld.kr)",
        "law": "부동산 가격공시에 관한 법률 제18조",
        "url": "https://www.realtyprice.kr",
    },
    "house": {
        "name": "개별주택 공시가격",
        "authority": "국토교통부",
        "provider": "한국부동산원",
        "system": "V-World 공간정보 오픈플랫폼 (vworld.kr)",
        "law": "부동산 가격공시에 관한 법률 제16조",
        "url": "https://www.realtyprice.kr",
    },
    "building": {
        "name": "주택외건물 시가표준액",
        "authority": "행정안전부 / 지방자치단체",
        "provider": "위택스(WeTax) / 서울시 ETAX",
        "system": "WeTax (wetax.go.kr) / 서울시 ETAX (etax.seoul.go.kr)",
        "law": "지방세법 제4조 (시가표준액)",
        "url": "https://www.wetax.go.kr",
    },
    "building_etax": {
        "name": "주택외건물 시가표준액 (서울)",
        "authority": "서울특별시",
        "provider": "서울특별시 ETAX",
        "system": "서울시 ETAX (etax.seoul.go.kr)",
        "law": "지방세법 제4조 (시가표준액)",
        "url": "https://etax.seoul.go.kr",
    },
    "building_wetax": {
        "name": "주택외건물 시가표준액",
        "authority": "행정안전부",
        "provider": "위택스(WeTax)",
        "system": "WeTax (wetax.go.kr)",
        "law": "지방세법 제4조 (시가표준액)",
        "url": "https://www.wetax.go.kr",
    },
    "commercial": {
        "name": "상업용 건물 기준시가",
        "authority": "국세청",
        "provider": "국세청 홈택스",
        "system": "국세청 홈택스 (hometax.go.kr)",
        "law": "소득세법 제99조, 상속세 및 증여세법 제61조",
        "url": "https://www.hometax.go.kr",
    },
    "factory": {
        "name": "공장 시가표준액",
        "authority": "행정안전부",
        "provider": "위택스(WeTax)",
        "system": "WeTax (wetax.go.kr)",
        "law": "지방세법 제4조 (시가표준액)",
        "url": "https://www.wetax.go.kr",
    },
}


class BaseLookupModule(ABC):

    @abstractmethod
    def search(self, address: dict, year: str = "", **kwargs) -> LookupResult:
        """조회를 수행하고 표준 결과를 반환한다."""

    @property
    @abstractmethod
    def property_type(self) -> str:
        ...

    @property
    @abstractmethod
    def property_type_label(self) -> str:
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...
