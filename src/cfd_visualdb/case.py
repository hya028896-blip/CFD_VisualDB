class CaseAPI:
    def __init__(self, database):
        self.database = database

    def list(self):
        return self.database.cases()

    def create(self, group_id: int, name: str) -> int:
        return self.database.create_case(group_id, name)

    def datasets(self, case_id: int):
        return self.database.datasets(case_id)

