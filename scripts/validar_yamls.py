"""Valida sintaxe e estrutura dos YAMLs de configuração."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

CONFIG_DIR = Path("config")


def validate_yaml(path: Path) -> bool:
    """Tenta carregar e valida estrutura mínima."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            raise ValueError("arquivo vazio ou inválido")

        if path.name.startswith("fluxo_"):
            assert "estados" in data, f"{path.name}: faltando 'estados'"
            assert "fluxo_id" in data, f"{path.name}: faltando 'fluxo_id'"
        elif path.name == "global.yaml":
            assert "identidade" in data, "faltando 'identidade'"
            assert "numeros" in data, "faltando 'numeros'"
            assert "planos" in data, "faltando 'planos'"

        print(f"  {path.name}")
        return True
    except Exception as e:
        print(f"  {path.name}: {e}")
        return False


if __name__ == "__main__":
    print("Validando YAMLs de configuração...\n")
    all_ok = True
    yaml_files = sorted(CONFIG_DIR.rglob("*.yaml"))

    if not yaml_files:
        print("Nenhum YAML encontrado em config/")
        sys.exit(1)

    for yaml_file in yaml_files:
        if not validate_yaml(yaml_file):
            all_ok = False

    total = len(yaml_files)
    print(f"\n{total} YAMLs verificados. {'Todos OK.' if all_ok else 'ERROS ENCONTRADOS.'}")
    sys.exit(0 if all_ok else 1)
