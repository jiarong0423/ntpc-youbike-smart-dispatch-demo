from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "public_shell" / "start_windows.cmd"
INSTALLER = ROOT / "INSTALL_AND_RUN_WINDOWS.cmd"
EXAMPLE = ROOT / "PUBLIC_RUNTIME_CONFIG.example.cmd"


@unittest.skip("Historical Windows compatibility; not part of the current Mac gate")
class WindowsConfigTests(unittest.TestCase):
    def test_launchers_use_script_relative_paths_and_lf(self) -> None:
        for path, anchor in (
            (INSTALLER, 'cd /d "%~dp0"'),
            (LAUNCHER, 'cd /d "%~dp0.."'),
        ):
            with self.subTest(path=path.name):
                data = path.read_bytes()
                self.assertNotIn(b"\r", data)
                self.assertFalse(data.startswith(b"\xef\xbb\xbf"))
                self.assertIn(anchor, data.decode("utf-8"))
                self.assertIn('"%VENV_DIR%\\Scripts\\python.exe"', data.decode("utf-8"))
        self.assertIn("* text eol=lf", (ROOT / ".gitattributes").read_text())

    def test_url_override_precedes_network_detection(self) -> None:
        text = LAUNCHER.read_text()
        override = text.index("if defined PUBLIC_TASK_BASE_URL goto url_ready")
        cloud_requirement = text.index("Cloud mode requires PUBLIC_TASK_BASE_URL")
        host_override = text.index("if defined PUBLIC_HOST goto host_ready")
        detection = text.index("Get-NetIPAddress")
        self.assertLess(override, cloud_requirement)
        self.assertLess(cloud_requirement, host_override)
        self.assertLess(host_override, detection)
        self.assertNotIn('set "PUBLIC_HOST=127.0.0.1"', text)
        self.assertIn("if not defined LAN_ADDRESS (", text)
        self.assertIn("Startup stopped", text)
        self.assertIn("DisableDelayedExpansion", text)

    def test_cloud_launch_has_no_local_database_argument(self) -> None:
        text = LAUNCHER.read_text()
        cloud = text.split(":cloud_runtime\n", 1)[1].split(":usage\n", 1)[0]
        self.assertIn("--task-backend cloud", cloud)
        self.assertIn('--public-task-base-url "%PUBLIC_TASK_BASE_URL%"', cloud)
        self.assertIn('--aws-profile "%YOUBIKE_AWS_PROFILE%"', cloud)
        self.assertIn('--aws-region "%YOUBIKE_AWS_REGION%"', cloud)
        self.assertNotIn("--aws-session-dir", cloud)
        self.assertNotIn("--task-db", cloud)
        self.assertNotIn("TASK_DB", cloud)
        self.assertNotIn("mkdir", cloud)
        self.assertNotIn("data\\sqlite", INSTALLER.read_text())
        self.assertLess(text.index('goto cloud_runtime'), text.index('set "TASK_DB='))

    def test_python_probes_are_sequential(self) -> None:
        text = INSTALLER.read_text()
        start = text.index("call :try_python 3.13")
        end = text.index(":try_python_path", start)
        probes = text[start:end]
        self.assertEqual(3, probes.count("if defined PYTHON_CMD goto python_ready"))
        self.assertLess(probes.index("3.13"), probes.index("3.12"))
        self.assertLess(probes.index("3.12"), probes.index("3.11"))

    def test_example_contains_only_nonsecret_configuration(self) -> None:
        self.assertTrue(EXAMPLE.is_file())
        self.assertFalse(any(ROOT.glob(".env*")))
        text = EXAMPLE.read_text()
        values = {}
        for line in text.splitlines():
            match = re.fullmatch(r'set "([A-Z_]+)=(.*)"', line)
            if match:
                values[match.group(1)] = match.group(2)
        self.assertEqual({"TASK_BACKEND", "PUBLIC_TASK_BASE_URL", "TASK_CLOUD_API_URL", "YOUBIKE_AWS_PROFILE", "YOUBIKE_AWS_REGION"}, set(values))
        self.assertEqual("local", values["TASK_BACKEND"])
        self.assertEqual("", values["YOUBIKE_AWS_PROFILE"])
        self.assertEqual("us-west-2", values["YOUBIKE_AWS_REGION"])
        self.assertNotRegex(text, r"(?i)(access.key|secret.key|session.token)\s*=")

    def test_cloud_profile_is_explicit_and_resource_region_is_fixed(self) -> None:
        text = LAUNCHER.read_text()
        self.assertIn("Cloud mode requires YOUBIKE_AWS_PROFILE", text)
        self.assertIn('set "YOUBIKE_AWS_REGION=us-west-2"', text)
        self.assertIn('if /I not "%YOUBIKE_AWS_REGION%"=="us-west-2"', text)
        self.assertNotRegex(text, r'--aws-profile\s+[^"%]')

    def test_lan_detection_policy_uses_unique_usable_ipv4(self) -> None:
        text = LAUNCHER.read_text()
        self.assertIn("Get-NetIPAddress -AddressFamily IPv4", text)
        self.assertIn("$_.AddressState -eq 'Preferred'", text)
        self.assertIn("'^(127\\.|169\\.254\\.|0\\.)'", text)
        self.assertIn("Sort-Object -Unique", text)
        self.assertIn("$ips.Count -ne 1", text)
        self.assertIn("[Console]::Error.WriteLine", text)
        self.assertRegex(text, r'for /f .+ in \(\x27powershell\.exe .+"\x27\) do set')

    @unittest.skipUnless(shutil.which("powershell.exe"), "Requires Windows PowerShell; static checks run on all platforms")
    def test_powershell_detection_with_mocked_interfaces(self) -> None:
        script = re.search(r'-Command "(.+)"\x27\) do set', LAUNCHER.read_text()).group(1)
        scenarios = (
            ([], 2, ""),
            (["127.0.0.1", "169.254.20.1"], 2, ""),
            (["127.0.0.1", "169.254.20.1", "192.168.20.8"], 0, "192.168.20.8"),
            (["192.168.20.8", "192.168.20.8"], 0, "192.168.20.8"),
            (["192.168.20.8", "10.10.0.2"], 2, ""),
        )
        for addresses, expected_exit, expected_address in scenarios:
            objects = "; ".join(
                "[pscustomobject]@{AddressState='Preferred'; IPAddress='" + address + "'}"
                for address in addresses
            )
            mock = "function Get-NetIPAddress { param($AddressFamily); " + objects + " }; "
            with self.subTest(addresses=addresses):
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", mock + script],
                    capture_output=True, text=True, timeout=20, check=False,
                )
                self.assertEqual(expected_exit, result.returncode, result.stderr)
                self.assertEqual(expected_address, result.stdout.strip())
                if expected_exit:
                    self.assertIn("Pass a LAN-IP", result.stderr)


if __name__ == "__main__":
    unittest.main()
