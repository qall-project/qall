# Copyright 2026 Scaleway
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import yaml

from dataclasses import dataclass, field
from dataclasses_json import dataclass_json
from pathlib import Path
from typing import Dict, Optional

from qall.object import ResourceProfile, AllowedResourceCollection


@dataclass_json
@dataclass
class LocalConfiguration:
    """
    Maps user-defined, dynamic profile keys (e.g., 'prod', 'dev', 'my-test')
    """

    profiles: Dict[str, ResourceProfile] = field(default_factory=dict)
    version: str = "1.0"

    @classmethod
    def create_default_configuration(
        cls, provider_name: str, filepath: Optional[Path | str] = None
    ) -> "LocalConfiguration":
        config = LocalConfiguration(
            version="1.0",
            profiles={
                "default": ResourceProfile(
                    provider=provider_name,
                    match_strategy="cheapest",
                    default=True,
                    allowed=AllowedResourceCollection(cpu=["*"], gpu=["*"], qpu=["*"]),
                )
            },
        )

        if filepath:
            config.to_yaml_file(filepath=filepath)

        return config

    @classmethod
    def from_yaml(cls, data: str) -> "LocalConfiguration":
        """
        Parses raw YAML string content into a LocalConfiguration object.

        Args:
            data: Raw string content from a .qall.yml configuration file.

        Returns:
            LocalConfiguration: Parsed configuration instance with safe fallbacks.

        Raises:
            ValueError: If the YAML content is invalid or does not deserialize into a dict.
        """
        if not data or not data.strip():
            return cls()

        try:
            parsed_dict = yaml.safe_load(data)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse configuration YAML: {e}") from e

        if parsed_dict is None:
            return cls()

        if not isinstance(parsed_dict, dict):
            raise ValueError(
                "Invalid configuration format: root document must be a YAML dictionary."
            )

        return cls.from_dict(parsed_dict)

    @classmethod
    def from_yaml_file(cls, filepath: Path | str) -> "LocalConfiguration":
        """Reads a qall.yml file and deserializes it into a structured Python object."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Qall configuration file not found at: {path}")

        with open(path, "r", encoding="utf-8") as f:
            # safe_load converts the YAML content into a standard Python dict structure
            yaml_data = yaml.safe_load(f)

        if not yaml_data or "profiles" not in yaml_data:
            raise ValueError(f"Invalid qall configuration file layout: {path}")

        return cls.from_dict(yaml_data)

    def to_yaml_file(self, filepath: Path | str) -> None:
        """Serializes the configuration object back into a clean YAML layout representation."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        data_dict = self.to_dict()

        with open(path, "w", encoding="utf-8") as f:
            # sort_keys=False preserves the declaration order for readability purposes
            yaml.safe_dump(data_dict, f, sort_keys=False, default_flow_style=False)

    def get_profile(self, profile_name: str) -> ResourceProfile:
        """Safely retrieves a configuration profile by name, raising a clean runtime error on missing hit."""
        if profile_name not in self.profiles:
            raise KeyError(
                f"Requested profile '{profile_name}' is not defined in the configurations. "
                f"Available profiles: {list(self.profiles.keys())}"
            )

        return self.profiles[profile_name]

    def get_default_profile(self) -> ResourceProfile:
        default_profile = list(filter(lambda p: p.default, self.profiles.values()))

        nb_profiles = len(default_profile)

        if nb_profiles == 0:
            return None

        if nb_profiles > 1:
            raise ValueError("Should have only one default profile")

        return default_profile[0]
