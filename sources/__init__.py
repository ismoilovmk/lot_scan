from .cooperation import CooperationCatalog
from .ebirja import Ebirja
from .tendergpt import TenderGpt
from .uzex_civil import UzexCivil
from .uzex_etender import UzexEtender
from .uzex_xarid import UzexAuction, UzexCompetition
from .xt_xarid import XtXarid

ALL_SOURCES = [UzexEtender(), UzexCivil(), UzexAuction(), UzexCompetition(), XtXarid(), TenderGpt(), Ebirja(),
               CooperationCatalog()]
