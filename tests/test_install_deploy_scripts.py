import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_HELPER_NAMES = (
    "install_with_providers.sh",
    "deploy_with_providers.sh",
    "install_with_cache.sh",
    "deploy_with_cache.sh",
    "repair_env_permissions.sh",
    "deploy_fix_telegram.sh",
    "provider_configure.py",
    "provider_preflight.py",
    "deploy_prepare.py",
    "telegram_healthcheck.py",
    "register_telegram_commands.py",
)


def test_install_and_deploy_scripts_pass_bash_syntax_check():
    for script in ("install_telegram_bot.sh", "deploy_telegram_bot.sh"):
        subprocess.run(["bash", "-n", str(ROOT / script)], check=True)


def test_only_two_supported_shell_scripts_exist():
    scripts = sorted(path.name for path in ROOT.glob("*.sh"))

    assert scripts == ["deploy_telegram_bot.sh", "install_telegram_bot.sh"]


def test_docs_do_not_reference_removed_helper_entrypoints_as_working_paths():
    docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in docs if path.is_file())

    for name in OLD_HELPER_NAMES:
        assert name not in combined
