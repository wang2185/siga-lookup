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
