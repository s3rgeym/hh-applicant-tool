import hh_applicant_tool

# Передаем аргументы как в команду
tool = hh_applicant_tool.HHApplicantTool()
print(tool.api_client.get("/me"))
