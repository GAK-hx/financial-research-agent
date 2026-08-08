from financial_research_agent.config import get_settings
from financial_research_agent.repositories.iceberg import IcebergAdmin


def main() -> None:
    created = IcebergAdmin(get_settings()).bootstrap_namespaces()
    if created:
        print(f"created namespaces: {', '.join(created)}")
    else:
        print("all namespaces already exist")


if __name__ == "__main__":
    main()
