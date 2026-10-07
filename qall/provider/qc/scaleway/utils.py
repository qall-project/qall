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
from qorus.provider.qc import QuantumContext


def get_session_dedup_from_context(context: QuantumContext):
    if not context.metadata:
        return None

    return context.metadata.get("deduplication_id", None)


def set_session_dedup_in_context(
    context: QuantumContext, deduplication_id: str
) -> QuantumContext:
    if not context.metadata:
        context.metadata = {}

    context.metadata["deduplication_id"] = deduplication_id

    return context


def add_session_id_in_context(context: QuantumContext, id: str) -> QuantumContext:
    if not context.metadata:
        context.metadata = {}

    sessions = context.metadata.get("sessions", None)

    if not sessions:
        sessions = [id]
    elif not id in sessions:
        sessions.append(id)

    context.metadata["sessions"] = sessions

    return context


def list_session_ids_from_context(context: QuantumContext) -> list[str]:
    if not context.metadata:
        return None

    return context.metadata.get("sessions", None)
