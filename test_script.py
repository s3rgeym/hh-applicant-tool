import hh_applicant_tool.main

# Передаем аргументы как в команду
tool = hh_applicant_tool.main.HHApplicantTool(["-vv"])
print(tool.api_client.get("/me"))
