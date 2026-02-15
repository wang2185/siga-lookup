"""공장 시가표준액 조회 — WeTax 재사용."""

from .base import BaseLookupModule, LookupResult
from .building_nonseoul import WeTaxModule


class FactoryModule(BaseLookupModule):

    def __init__(self):
        self._wetax = WeTaxModule()

    @property
    def property_type(self) -> str:
        return "factory"

    @property
    def property_type_label(self) -> str:
        return "공장 (시가표준액)"

    @property
    def source_name(self) -> str:
        return "wetax"

    def search(self, address: dict, year: str = "", **kwargs) -> LookupResult:
        return self._wetax.search(
            address, year,
            building_type="factory",
            override_type=self.property_type,
            override_label=self.property_type_label,
            **kwargs,
        )
