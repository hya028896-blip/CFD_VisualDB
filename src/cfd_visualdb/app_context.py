from dataclasses import dataclass

from .case import CaseAPI
from .database import DatabaseAPI
from .roi import ROIAPI
from .viewer import ViewerAPI


@dataclass
class AppContext:
    database: DatabaseAPI
    viewer: ViewerAPI
    roi: ROIAPI
    case: CaseAPI

    @classmethod
    def create(cls, database_path):
        database = DatabaseAPI(database_path)
        database.ensure_defaults()
        return cls(database=database, viewer=ViewerAPI(), roi=ROIAPI(database), case=CaseAPI(database))

