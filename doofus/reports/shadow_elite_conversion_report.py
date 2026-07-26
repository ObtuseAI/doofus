"""Shadow elite conversion report."""
from doofus.evolution.shadow_elite_archive import get_shadow_elite_archive
import json

def main():
    print(json.dumps(get_shadow_elite_archive(), indent=2))

if __name__ == "__main__":
    main()
