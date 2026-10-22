"""Tipi di parametro condivisi tra i router.

I form GET dei filtri inviano sempre il campo, anche quando l'opzione scelta è
"tutti" (``value=""``): un ``int | None`` puro fallirebbe con 422. ``OptInt``
normalizza la stringa vuota a ``None`` prima della validazione.
"""
from typing import Annotated

from pydantic import BeforeValidator

OptInt = Annotated[int | None, BeforeValidator(lambda v: None if v == "" else v)]
