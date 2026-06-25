# Citry port of the django-components large benchmark scenario
# (test_benchmark_djc.py, vendored in this directory): the same project page
# (35 components, the same data, JS/CSS dependencies, provide/inject, slots,
# and dynamic elements), expressed in citry. The benchmark harness reads this
# file as a source string and slices it at the markers below, so the code
# outside the pytest section must stay self-contained. See
# docs/design/benchmarking.md.
#
# Faithfulness notes (docs/design/benchmarking.md section 6.2):
# - Django form rendering is hand-written here (Django's form widgets render
#   through Django's own template engine, which we must not pull into a citry
#   measurement).
# - Django-only helpers (naturaltime, csrf, the request object) are small
#   local stand-ins, so this file imports no Django and the import-time
#   benchmark stays honest.
# - DJC filters (`|json`, `|alpine`, ...) become plain functions, injected
#   into every component's template scope by a small extension.

from __future__ import annotations

import difflib
import json
from dataclasses import MISSING, dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from inspect import signature
from types import MappingProxyType, SimpleNamespace
from typing import Any, Callable, Iterable, Literal, NamedTuple, TypeAlias, TypedDict, TypeVar

import wrapt

from citry import Citry, Component
from citry.util.html import SafeString, escape

# ----------- IMPORTS END ------------ #

# This is the plain citry variant. The Const optimization is exercised by a
# separate file, test_benchmark_citry_const.py, which marks each component's
# render-invariant literals Const (docs/design/benchmarking.md section 6.4).

T = TypeVar("T")
U = TypeVar("U")


#####################################
# DJANGO STAND-INS
#####################################
# Tiny local replacements so this file imports no Django (the import-time
# benchmark must measure citry, not Django). Each covers only what the
# scenario actually reads.


def now() -> datetime:
    return datetime.now(tz=timezone.utc)


def naturaltime(value: Any) -> str:
    """A minimal stand-in for django.contrib.humanize's naturaltime."""
    if not isinstance(value, datetime):
        return str(value)
    delta = now() - value
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "a moment ago"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    if seconds < 86400:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86400} days ago"


def make_request(user: Any) -> SimpleNamespace:
    """Stand-in for django.http.HttpRequest, carrying only the read fields."""
    return SimpleNamespace(user=user, method="GET", path="/projects/1")


def get_csrf_token(_request: Any) -> str:
    """Stand-in for django.middleware.csrf.get_token (a fixed fake token)."""
    return "benchmarkcsrftoken0000000000000000"


#####################################
# TEMPLATE HELPERS (DJC filters as functions)
#####################################
# In V3 there is no filter syntax; these are plain functions called from
# `template_data` (Python), never from templates.


def _plain(value: Any) -> Any:
    """
    Strip Const markers (transparent proxies) recursively.

    json.dumps and other C-level APIs reject the proxy, and the scenario marks
    inputs Const in const mode (and static attrs are auto-marked anyway), so
    the serializing helpers unwrap first. See docs/design/constness.md.
    """
    if isinstance(value, wrapt.ObjectProxy):
        value = value.__wrapped__
    if isinstance(value, dict):
        return {_plain(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def to_alpine_json(value: Any) -> str:
    """Serialize for an Alpine attribute; single quotes so it survives in HTML."""
    return json.dumps(_plain(value)).replace('"', "'")


def to_json(value: Any) -> str:
    return json.dumps(_plain(value))


def get_item(dictionary: Any, key: Any) -> Any:
    return dictionary.get(key)


def serialize_to_js(obj: Any) -> str:
    """Serialize a Python object to a JS-like expression (recursive)."""
    obj = _plain(obj)
    if isinstance(obj, dict):
        items = [f"{key}: {serialize_to_js(value)}" for key, value in obj.items()]
        return f"{{ {', '.join(items)} }}"
    if isinstance(obj, (list, tuple)):
        return f"[{', '.join(serialize_to_js(item) for item in obj)}]"
    if isinstance(obj, str):
        return obj
    return str(obj)


def default_if_none(value: Any, fallback: Any) -> Any:
    return fallback if value is None else value


def title_case(value: Any) -> str:
    return str(value).title()


def linebreaksbr(value: Any) -> str:
    return str(value).replace("\n", "<br>")


# The DJC filters above (to_json, to_alpine_json, ...) are plain functions
# called from `template_data`, the idiomatic citry shape: data is shaped in
# Python and the template only references the resulting variables. So nothing
# is injected into the template scope, and templates carry no filter/helper
# calls (V3 has no filter syntax by design).

app = Citry()


data_json = """
{
  "project": {
    "pk": 1,
    "fields": {
      "name": "Project Name",
      "organization": 1,
      "status": "INPROGRESS",
      "start_date": "2022-02-06",
      "end_date": "2024-02-07"
    }
  },
  "project_tags": [],
  "phases": [
    {
      "pk": 8,
      "fields": {
        "project": 1,
        "phase_template": 3
      }
    },
    {
      "pk": 7,
      "fields": {
        "project": 1,
        "phase_template": 4
      }
    },
    {
      "pk": 6,
      "fields": {
        "project": 1,
        "phase_template": 5
      }
    },
    {
      "pk": 5,
      "fields": {
        "project": 1,
        "phase_template": 6
      }
    },
    {
      "pk": 4,
      "fields": {
        "project": 1,
        "phase_template": 2
      }
    }
  ],
  "notes_1": [
    {
      "pk": 1,
      "fields": {
        "created": "2025-02-07T08:59:58.689Z",
        "modified": "2025-02-07T08:59:58.689Z",
        "project": 1,
        "text": "Test note 1"
      }
    },
    {
      "pk": 2,
      "fields": {
        "created": "2025-02-07T08:59:58.689Z",
        "modified": "2025-02-07T08:59:58.689Z",
        "project": 1,
        "text": "Test note 2"
      }
    }
  ],
  "comments_by_notes_1": {
    "1": [
      {
        "pk": 3,
        "fields": {
          "parent": 1,
          "notes": "Test note one two three",
          "modified_by": 1
        }
      },
      {
        "pk": 4,
        "fields": {
          "parent": 1,
          "notes": "Test note 2",
          "modified_by": 1
        }
      }
    ]
  },
  "notes_2": [
    {
      "pk": 1,
      "fields": {
        "created": "2024-02-07T11:20:49.085Z",
        "modified": "2024-02-07T11:20:55.003Z",
        "project": 1,
        "text": "Test note x"
      }
    }
  ],
  "comments_by_notes_2": {
    "1": [
      {
        "pk": 1,
        "fields": {
          "parent": 1,
          "text": "Test note 6",
          "modified_by": 1
        }
      },
      {
        "pk": 2,
        "fields": {
          "parent": 1,
          "text": "Test note 5",
          "modified_by": 1
        }
      },
      {
        "pk": 4,
        "fields": {
          "parent": 1,
          "text": "Test note 4",
          "modified_by": 1
        }
      },
      {
        "pk": 6,
        "fields": {
          "parent": 1,
          "text": "Test note 3",
          "modified_by": 1
        }
      }
    ]
  },
  "notes_3": [
    {
      "pk": 2,
      "fields": {
        "created": "2024-02-07T11:20:49.085Z",
        "modified": "2024-02-07T11:20:55.003Z",
        "project": 1,
        "text": "Test note 2"
      }
    }
  ],
  "comments_by_notes_3": {
    "2": [
      {
        "pk": 1,
        "fields": {
          "parent": 2,
          "text": "Test note 1",
          "modified_by": 1
        }
      },
      {
        "pk": 3,
        "fields": {
          "parent": 2,
          "text": "Test note 0",
          "modified_by": 1
        }
      }
    ]
  },
  "roles_with_users": [
    {
      "pk": 6,
      "fields": {
        "user": 2,
        "project": 1,
        "name": "Assistant"
      }
    },
    {
      "pk": 7,
      "fields": {
        "user": 2,
        "project": 1,
        "name": "Owner"
      }
    }
  ],
  "contacts": [],
  "outputs": [
    [
      {
        "pk": 14,
        "fields": {
          "name": "Lorem ipsum 16",
          "description": "",
          "completed": false,
          "phase": 8,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 15,
        "fields": {
          "name": "Lorem ipsum 15",
          "description": "",
          "completed": false,
          "phase": 8,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 16,
        "fields": {
          "name": "Lorem ipsum 14",
          "description": "",
          "completed": false,
          "phase": 8,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 17,
        "fields": {
          "name": "Lorem ipsum 13",
          "description": "",
          "completed": false,
          "phase": 8,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 18,
        "fields": {
          "name": "Lorem ipsum 12",
          "description": "",
          "completed": true,
          "phase": 4,
          "dependency": null
        }
      },
      [
        [
          {
            "pk": 19,
            "fields": {
              "text": "Test bookmark",
              "url": "http://localhost:8000/create/bookmmarks/9/",
              "created_by": 1,
              "output": 18
            }
          },
          []
        ]
      ],
      []
    ],
    [
      {
        "pk": 20,
        "fields": {
          "name": "Lorem ipsum 11",
          "description": "",
          "completed": false,
          "phase": 7,
          "dependency": 14
        }
      },
      [],
      [
        [
          {
            "pk": 14,
            "fields": {
              "name": "Lorem ipsum 10",
              "description": "",
              "completed": false,
              "phase": 8,
              "dependency": null
            }
          },
          []
        ]
      ]
    ],
    [
      {
        "pk": 21,
        "fields": {
          "name": "Lorem ipsum 9",
          "description": "",
          "completed": false,
          "phase": 7,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 22,
        "fields": {
          "name": "Lorem ipsum 8",
          "description": "",
          "completed": false,
          "phase": 7,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 23,
        "fields": {
          "name": "Lorem ipsum 7",
          "description": "",
          "completed": false,
          "phase": 7,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 24,
        "fields": {
          "name": "Lorem ipsum 6",
          "description": "",
          "completed": false,
          "phase": 7,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 25,
        "fields": {
          "name": "Lorem ipsum 5",
          "description": "",
          "completed": false,
          "phase": 6,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 26,
        "fields": {
          "name": "Lorem ipsum 4",
          "description": "",
          "completed": false,
          "phase": 6,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 27,
        "fields": {
          "name": "Lorem ipsum 3",
          "description": "",
          "completed": false,
          "phase": 5,
          "dependency": null
        }
      },
      [],
      []
    ],
    [
      {
        "pk": 28,
        "fields": {
          "name": "Lorem ipsum 2",
          "description": "",
          "completed": false,
          "phase": 7,
          "dependency": 14
        }
      },
      [],
      [
        [
          {
            "pk": 14,
            "fields": {
              "name": "Lorem ipsum 1",
              "description": "",
              "completed": false,
              "phase": 8,
              "dependency": null
            }
          },
          []
        ]
      ]
    ]
  ],
  "status_updates": [],
  "user_is_project_member": true,
  "user_is_project_owner": true,
  "phase_titles": {
    "PHASE_0": "Phase 0",
    "PHASE_1": "Phase 1",
    "PHASE_2": "Phase 2",
    "PHASE_3": "Phase 3",
    "PHASE_4": "Phase 4",
    "PHASE_5": "Phase 5",
    "LEGACY": "Legacy"
  },
  "users": [
    {
      "pk": 2,
      "fields": {
        "name": "UserName",
        "is_staff": true
      }
    }
  ],
  "organizations": [
    {
      "pk": 1,
      "fields": {
        "created": "2025-02-07T16:27:49.837Z",
        "modified": "2025-02-07T16:27:49.837Z",
        "name": "Org Name"
      }
    }
  ],
  "phase_templates": [
    {
      "pk": 3,
      "fields": {
        "created": "2025-02-07T16:27:49.837Z",
        "modified": "2025-02-07T16:27:49.837Z",
        "name": "Phase 3",
        "description": "## Phase 3",
        "type": "PHASE_3"
      }
    },
    {
      "pk": 4,
      "fields": {
        "created": "2025-02-07T16:27:49.837Z",
        "modified": "2025-02-07T16:27:49.837Z",
        "name": "Phase 2",
        "description": "## Phase 2",
        "type": "PHASE_2"
      }
    },
    {
      "pk": 5,
      "fields": {
        "created": "2025-02-07T16:27:49.837Z",
        "modified": "2025-02-07T16:27:49.837Z",
        "name": "Phase 4",
        "description": "## Phase 4",
        "type": "PHASE_4"
      }
    },
    {
      "pk": 6,
      "fields": {
        "created": "2025-02-07T16:27:49.837Z",
        "modified": "2025-02-07T16:27:49.837Z",
        "name": "Phase 5",
        "description": "## Phase 5",
        "type": "PHASE_5"
      }
    },
    {
      "pk": 2,
      "fields": {
        "created": "2025-02-07T16:27:49.837Z",
        "modified": "2025-02-07T16:27:49.837Z",
        "name": "Phase 1",
        "description": "## Phase 1",
        "type": "PHASE_1"
      }
    }
  ]
}
"""


# DATA LOADER
#####################################


def load_project_data_from_json(contents: str) -> dict:
    """
    Load project data from JSON and resolves references between objects.
    Returns the data with all resolvable references replaced with actual object references.
    """
    data = json.loads(contents)

    # First create lookup tables for objects that will be referenced
    users_by_id = {user["pk"]: {"id": user["pk"], **user["fields"]} for user in data.get("users", [])}

    def _get_user(user_id: int):
        return users_by_id[user_id] if user_id in users_by_id else data.get("users", [])[0]

    organizations_by_id = {org["pk"]: {"id": org["pk"], **org["fields"]} for org in data.get("organizations", [])}

    phase_templates_by_id = {pt["pk"]: {"id": pt["pk"], **pt["fields"]} for pt in data.get("phase_templates", [])}

    # 1. Resolve project's organization reference
    project = {"id": data["project"]["pk"], **data["project"]["fields"]}
    if "organization" in project:
        org_id = project.pop("organization")  # Remove the ID field
        project["organization"] = organizations_by_id[org_id]  # Add the reference

    # 2. Project tags - no changes needed
    project_tags = data["project_tags"]

    # 3. Resolve phases' references
    phases = []
    phases_by_id = {}  # We'll need this for resolving output references later
    for phase_data in data["phases"]:
        phase = {"id": phase_data["pk"], **phase_data["fields"]}
        if "project" in phase:
            phase["project"] = project
        if "phase_template" in phase:
            template_id = phase.pop("phase_template")
            phase["phase_template"] = phase_templates_by_id[template_id]
        phases.append(phase)
        phases_by_id[phase["id"]] = phase

    # 4. Resolve notes_1 references
    notes_1 = []
    notes_1_by_id = {}  # We'll need this for resolving notes references
    for note_data in data["notes_1"]:
        note = {"id": note_data["pk"], **note_data["fields"]}
        if "project" in note:
            note["project"] = project
        notes_1.append(note)
        notes_1_by_id[note["id"]] = note

    # 5. Resolve comments_by_notes_1 references
    comments_by_notes_1 = {}
    for note_id, comments_list in data["comments_by_notes_1"].items():
        resolved_comments = []
        for comment_data in comments_list:
            comment = {"id": comment_data["pk"], **comment_data["fields"]}
            if "modified_by" in comment:
                comment["modified_by"] = _get_user(comment["modified_by"])
            if "parent" in comment:
                comment["parent"] = notes_1_by_id[comment["parent"]]
            resolved_comments.append(comment)
        comments_by_notes_1[note_id] = resolved_comments

    # 6. Resolve notes_2' references
    notes_2 = []
    notes_2_by_id = {}  # We'll need this for resolving notes references
    for note_data in data["notes_2"]:
        note = {"id": note_data["pk"], **note_data["fields"]}
        if "project" in note:
            note["project"] = project
        notes_2.append(note)
        notes_2_by_id[note["id"]] = note

    # 7. Resolve comments_by_notes_2 references
    comments_by_notes_2 = {}
    for note_id, comments_list in data["comments_by_notes_2"].items():
        resolved_comments = []
        for comment_data in comments_list:
            comment = {"id": comment_data["pk"], **comment_data["fields"]}
            if "modified_by" in comment:
                comment["modified_by"] = _get_user(comment["modified_by"])
            if "parent" in comment:
                comment["parent"] = notes_2_by_id[comment["parent"]]
            resolved_comments.append(comment)
        comments_by_notes_2[note_id] = resolved_comments

    # 8. Resolve notes_3 references
    notes_3 = []
    notes_3_by_id = {}  # We'll need this for resolving notes references
    for note_data in data["notes_3"]:
        note = {"id": note_data["pk"], **note_data["fields"]}
        if "project" in note:
            note["project"] = project
        notes_3.append(note)
        notes_3_by_id[note["id"]] = note

    # 9. Resolve comments_by_notes_3 references
    comments_by_notes_3 = {}
    for note_id, comments_list in data["comments_by_notes_3"].items():
        resolved_comments = []
        for comment_data in comments_list:
            comment = {"id": comment_data["pk"], **comment_data["fields"]}
            if "modified_by" in comment:
                comment["modified_by"] = _get_user(comment["modified_by"])
            if "parent" in comment:
                comment["parent"] = notes_3_by_id[comment["parent"]]
            resolved_comments.append(comment)
        comments_by_notes_3[note_id] = resolved_comments

    # 10. Resolve roles_with_users references
    roles = []
    for role_data in data["roles_with_users"]:
        role = {"id": role_data["pk"], **role_data["fields"]}
        if "project" in role:
            role["project"] = project
        if "user" in role:
            role["user"] = _get_user(role["user"])
        roles.append(role)

    # 11. Contacts - EMPTY, so no changes needed
    contacts = data["contacts"]

    # 12. Resolve outputs references
    resolved_outputs = []
    outputs_by_id = {}  # For resolving dependencies

    # First pass: Create all output objects and build lookup
    for output_tuple in data["outputs"]:
        output_data = output_tuple[0]
        output = {"id": output_data["pk"], **output_data["fields"]}
        if "phase" in output:
            output["phase"] = phases_by_id[output["phase"]]
        outputs_by_id[output["id"]] = output

    # Second pass: Process each output with its attachments and dependencies
    for output_tuple in data["outputs"]:
        output_data, attachments_data, dependencies_data = output_tuple
        output = outputs_by_id[output_data["pk"]]

        # Process attachments
        resolved_attachments = []
        for attachment_tuple in attachments_data:
            attachment_data = attachment_tuple[0]
            attachment = {"id": attachment_data["pk"], **attachment_data["fields"]}
            if "created_by" in attachment:
                attachment["created_by"] = _get_user(attachment["created_by"])
            if "output" in attachment:
                attachment["output"] = outputs_by_id[attachment["output"]]
            # Keep tags as is
            resolved_attachments.append((attachment, attachment_tuple[1]))

        # Process dependencies
        resolved_dependencies = []
        for dep_tuple in dependencies_data:
            dep_data = dep_tuple[0]
            dep_output = outputs_by_id[dep_data["pk"]]
            # Keep the tuple structure but with resolved references
            resolved_dependencies.append((dep_output, dep_tuple[1]))

        resolved_outputs.append((output, resolved_attachments, resolved_dependencies))

    return {
        "project": project,
        "project_tags": project_tags,
        "phases": phases,
        "notes_1": notes_1,
        "comments_by_notes_1": comments_by_notes_1,
        "notes_2": notes_2,
        "comments_by_notes_2": comments_by_notes_2,
        "notes_3": notes_3,
        "comments_by_notes_3": comments_by_notes_3,
        "roles_with_users": roles,
        "contacts": contacts,
        "outputs": resolved_outputs,
        "status_updates": data["status_updates"],
        "user_is_project_member": data["user_is_project_member"],
        "user_is_project_owner": data["user_is_project_owner"],
        "phase_titles": data["phase_titles"],
        "users": data["users"],
    }




#####################################
# TYPES
#####################################


class User(TypedDict):
    id: int
    name: str


class Organization(TypedDict):
    id: int
    name: str


class Project(TypedDict):
    id: int
    name: str
    organization: Organization
    status: str
    start_date: date
    end_date: date


class ProjectRole(TypedDict):
    id: int
    user: User
    project: Project
    name: str


class ProjectBookmark(TypedDict):
    id: int
    project: Project
    text: str
    url: str
    attachment: "ProjectOutputAttachment | None"


class ProjectStatusUpdate(TypedDict):
    id: int
    project: Project
    text: str
    modified_by: User
    modified: str


class ProjectContact(TypedDict):
    id: int
    project: Project
    link_id: str
    name: str
    job: str


class PhaseTemplate(TypedDict):
    id: int
    name: str
    description: str
    type: str


class ProjectPhase(TypedDict):
    id: int
    project: Project
    phase_template: PhaseTemplate


class ProjectOutput(TypedDict):
    id: int
    name: str
    description: str
    completed: bool
    phase: ProjectPhase
    dependency: "ProjectOutput | None"


class ProjectOutputAttachment(TypedDict):
    id: int
    text: str
    url: str
    created_by: User
    output: ProjectOutput


class ProjectNote(TypedDict):
    id: int
    project: Project
    text: str
    created: str


class ProjectNoteComment(TypedDict):
    id: int
    parent: ProjectNote
    text: str
    modified_by: User
    modified: str



#####################################
# CONSTANTS
#####################################

FORM_SHORT_TEXT_MAX_LEN = 255


# This allows us to compare Enum values against strings
class StrEnum(str, Enum):
    pass


class TagResourceType(StrEnum):
    PROJECT = "PROJECT"
    PROJECT_BOOKMARK = "PROJECT_BOOKMARK"
    PROJECT_OUTPUT = "PROJECT_OUTPUT"
    PROJECT_OUTPUT_ATTACHMENT = "PROJECT_OUTPUT_ATTACHMENT"
    PROJECT_TEMPLATE = "PROJECT_TEMPLATE"


class ProjectPhaseType(StrEnum):
    PHASE_1 = "PHASE_1"
    PHASE_2 = "PHASE_2"
    PHASE_3 = "PHASE_3"
    PHASE_4 = "PHASE_4"
    PHASE_5 = "PHASE_5"


class TagTypeMeta(NamedTuple):
    allowed_values: tuple[str, ...]


# Additional metadata for Tags
#
# NOTE: We use MappingProxyType as an immutable dict.
#       See https://stackoverflow.com/questions/2703599
TAG_TYPE_META = MappingProxyType(
    {
        TagResourceType.PROJECT: TagTypeMeta(
            allowed_values=(
                "Tag 1",
                "Tag 2",
                "Tag 3",
                "Tag 4",
            ),
        ),
        TagResourceType.PROJECT_BOOKMARK: TagTypeMeta(
            allowed_values=(
                "Tag 5",
                "Tag 6",
                "Tag 7",
                "Tag 8",
            ),
        ),
        TagResourceType.PROJECT_OUTPUT: TagTypeMeta(
            allowed_values=(),
        ),
        TagResourceType.PROJECT_OUTPUT_ATTACHMENT: TagTypeMeta(
            allowed_values=(
                "Tag 9",
                "Tag 10",
                "Tag 11",
                "Tag 12",
                "Tag 13",
                "Tag 14",
                "Tag 15",
                "Tag 16",
                "Tag 17",
                "Tag 18",
                "Tag 19",
                "Tag 20",
            ),
        ),
        TagResourceType.PROJECT_TEMPLATE: TagTypeMeta(
            allowed_values=("Tag 21",),
        ),
    },
)


class ProjectOutputDef(NamedTuple):
    title: str
    description: str | None = None
    dependency: str | None = None


class ProjectPhaseMeta(NamedTuple):
    type: ProjectPhaseType
    outputs: list[ProjectOutputDef]


# This constant decides in which order the project phases are shown,
# as well as what kind of name of description they have.
#
# NOTE: We use MappingProxyType as an immutable dict.
#       See https://stackoverflow.com/questions/2703599
PROJECT_PHASES_META = MappingProxyType(
    {
        ProjectPhaseType.PHASE_1: ProjectPhaseMeta(
            type=ProjectPhaseType.PHASE_1,
            outputs=[
                ProjectOutputDef(title="Lorem ipsum 0"),
            ],
        ),
        ProjectPhaseType.PHASE_2: ProjectPhaseMeta(
            type=ProjectPhaseType.PHASE_2,
            outputs=[
                ProjectOutputDef(title="Lorem ipsum 1"),
                ProjectOutputDef(title="Lorem ipsum 2"),
                ProjectOutputDef(title="Lorem ipsum 3"),
                ProjectOutputDef(title="Lorem ipsum 4"),
            ],
        ),
        ProjectPhaseType.PHASE_3: ProjectPhaseMeta(
            type=ProjectPhaseType.PHASE_3,
            outputs=[
                ProjectOutputDef(
                    title="Lorem ipsum 6",
                    dependency="Lorem ipsum 1",
                ),
                ProjectOutputDef(
                    title="Lorem ipsum 7",
                    dependency="Lorem ipsum 1",
                ),
                ProjectOutputDef(title="Lorem ipsum 8"),
                ProjectOutputDef(title="Lorem ipsum 9"),
                ProjectOutputDef(title="Lorem ipsum 10"),
                ProjectOutputDef(title="Lorem ipsum 11"),
            ],
        ),
        ProjectPhaseType.PHASE_4: ProjectPhaseMeta(
            type=ProjectPhaseType.PHASE_4,
            outputs=[
                ProjectOutputDef(title="Lorem ipsum 12"),
                ProjectOutputDef(title="Lorem ipsum 13"),
            ],
        ),
        ProjectPhaseType.PHASE_5: ProjectPhaseMeta(
            type=ProjectPhaseType.PHASE_5,
            outputs=[
                ProjectOutputDef(title="Lorem ipsum 14"),
            ],
        ),
    },
)


#####################################
# THEME
#####################################

ThemeColor: TypeAlias = Literal["default", "error", "success", "alert", "info"]
ThemeVariant: TypeAlias = Literal["primary", "secondary"]

VARIANTS = ["primary", "secondary"]


class ThemeStylingUnit(NamedTuple):
    """
    Smallest unit of info, this class defines a specific styling of a specific
    component in a specific state.

    E.g. styling of a disabled "Error" button.
    """

    color: str
    """CSS class(es) specifying color"""
    css: str = ""
    """Other CSS classes not specific to color"""


class ThemeStylingVariant(NamedTuple):
    """
    Collection of styling combinations that are meaningful as a group.

    E.g. all "error" variants - primary, disabled, secondary, ...
    """

    primary: ThemeStylingUnit
    primary_disabled: ThemeStylingUnit
    secondary: ThemeStylingUnit
    secondary_disabled: ThemeStylingUnit


class Theme(NamedTuple):
    """Class for defining a styling and color theme for the app."""

    default: ThemeStylingVariant
    error: ThemeStylingVariant
    alert: ThemeStylingVariant
    success: ThemeStylingVariant
    info: ThemeStylingVariant

    sidebar: str
    sidebar_link: str
    background: str
    tab_active: str
    tab_text_active: str
    tab_text_inactive: str
    check_interactive: str
    check_static: str
    check_outline: str


_secondary_btn_styling = "ring-1 ring-inset"

theme = Theme(
    default=ThemeStylingVariant(
        primary=ThemeStylingUnit(
            color="bg-blue-600 text-white hover:bg-blue-500 focus-visible:outline-blue-600 transition",
        ),
        primary_disabled=ThemeStylingUnit(
            color="bg-blue-300 text-blue-50 focus-visible:outline-blue-600 transition",
        ),
        secondary=ThemeStylingUnit(
            color="bg-white text-gray-800 ring-gray-300 hover:bg-gray-100 focus-visible:outline-gray-600 transition",
            css=_secondary_btn_styling,
        ),
        secondary_disabled=ThemeStylingUnit(
            color="bg-white text-gray-300 ring-gray-300 focus-visible:outline-gray-600 transition",
            css=_secondary_btn_styling,
        ),
    ),
    error=ThemeStylingVariant(
        primary=ThemeStylingUnit(
            color="bg-red-600 text-white hover:bg-red-500 focus-visible:outline-red-600",
        ),
        primary_disabled=ThemeStylingUnit(
            color="bg-red-300 text-white focus-visible:outline-red-600",
        ),
        secondary=ThemeStylingUnit(
            color="bg-white text-red-600 ring-red-300 hover:bg-red-100 focus-visible:outline-red-600",
            css=_secondary_btn_styling,
        ),
        secondary_disabled=ThemeStylingUnit(
            color="bg-white text-red-200 ring-red-100 focus-visible:outline-red-600",
            css=_secondary_btn_styling,
        ),
    ),
    alert=ThemeStylingVariant(
        primary=ThemeStylingUnit(
            color="bg-amber-500 text-white hover:bg-amber-400 focus-visible:outline-amber-500",
        ),
        primary_disabled=ThemeStylingUnit(
            color="bg-amber-100 text-orange-300 focus-visible:outline-amber-500",
        ),
        secondary=ThemeStylingUnit(
            color="bg-white text-amber-500 ring-amber-300 hover:bg-amber-100 focus-visible:outline-amber-500",
            css=_secondary_btn_styling,
        ),
        secondary_disabled=ThemeStylingUnit(
            color="bg-white text-orange-200 ring-amber-100 focus-visible:outline-amber-500",
            css=_secondary_btn_styling,
        ),
    ),
    success=ThemeStylingVariant(
        primary=ThemeStylingUnit(
            color="bg-green-600 text-white hover:bg-green-500 focus-visible:outline-green-600",
        ),
        primary_disabled=ThemeStylingUnit(
            color="bg-green-300 text-white focus-visible:outline-green-600",
        ),
        secondary=ThemeStylingUnit(
            color="bg-white text-green-600 ring-green-300 hover:bg-green-100 focus-visible:outline-green-600",
            css=_secondary_btn_styling,
        ),
        secondary_disabled=ThemeStylingUnit(
            color="bg-white text-green-200 ring-green-100 focus-visible:outline-green-600",
            css=_secondary_btn_styling,
        ),
    ),
    info=ThemeStylingVariant(
        primary=ThemeStylingUnit(
            color="bg-sky-600 text-white hover:bg-sky-500 focus-visible:outline-sky-600",
        ),
        primary_disabled=ThemeStylingUnit(
            color="bg-sky-300 text-white focus-visible:outline-sky-600",
        ),
        secondary=ThemeStylingUnit(
            color="bg-white text-sky-600 ring-sky-300 hover:bg-sky-100 focus-visible:outline-sky-600",
            css=_secondary_btn_styling,
        ),
        secondary_disabled=ThemeStylingUnit(
            color="bg-white text-sky-200 ring-sky-100 focus-visible:outline-sky-600",
            css=_secondary_btn_styling,
        ),
    ),
    sidebar="bg-neutral-900 text-neutral-200",
    sidebar_link="hover:bg-neutral-700 hover:text-white transition",
    background="bg-neutral-200",
    tab_active="border-blue-700",
    tab_text_active="text-blue-700",
    tab_text_inactive="text-gray-500 hover:text-blue-700",
    check_interactive="bg-blue-600 group-hover:bg-blue-500 transition",
    check_static="bg-blue-600",
    check_outline="border-2 border-blue-600 bg-white",
)


def get_styling_css(
    variant: "ThemeVariant | None" = None,
    color: "ThemeColor | None" = None,
    disabled: bool | None = None,
):
    """
    Dynamically access CSS styling classes for a specific variant and state.

    E.g. following two calls get styling classes for:
    1. Secondary error state
    1. Secondary alert disabled state
    2. Primary default disabled state
    ```py
    get_styling_css('secondary', 'error')
    get_styling_css('secondary', 'alert', disabled=True)
    get_styling_css(disabled=True)
    ```
    """
    variant = variant or "primary"
    color = color or "default"
    disabled = disabled if disabled is not None else False

    color_variants: ThemeStylingVariant = getattr(theme, str(color))

    if variant not in VARIANTS:
        raise ValueError(
            f'Unknown theme variant "{variant}", must be one of {VARIANTS}',
        )

    variant_name = variant if not disabled else f"{variant}_disabled"
    styling: ThemeStylingUnit = getattr(color_variants, str(variant_name))

    css = f"{styling.color} {styling.css}".strip()
    return css




def group_by(
    lst: Iterable[T],
    keyfn: Callable[[T, int], Any],
    mapper: Callable[[T, int], U] | None = None,
):
    """
    Given a list, generates a key for each item in the list using the `keyfn`.

    Returns a dictionary of generated keys, where each value is a list of corresponding
    items.

    Similar to Lodash's `groupby`.

    Optionally map the values in the lists with `mapper`.
    """
    grouped: dict[Any, list[U | T]] = {}
    for index, item in enumerate(lst):
        key = dynamic_apply(keyfn, item, index)
        if key not in grouped:
            grouped[key] = []

        mapped_item = dynamic_apply(mapper, item, index) if mapper else item
        grouped[key].append(mapped_item)
    return grouped


def dynamic_apply(fn: Callable, *args):
    """
    Given a function and positional arguments that should be applied to given function,
    this helper will apply only as many arguments as the function defines, or only
    as much as the number of arguments that we can apply.
    """
    mapper_args_count = len(signature(fn).parameters)
    num_args_to_apply = min(mapper_args_count, len(args))
    first_n_args = args[:num_args_to_apply]

    return fn(*first_n_args)


#####################################
# TIMESTAMP HELPER
#####################################


def format_timestamp(timestamp: Any) -> str:
    """More than 7 days ago -> "Jan 1, 2025"; otherwise a relative string."""
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    if now() - timestamp > timedelta(days=7):
        return timestamp.strftime("%b %-d, %Y")
    return naturaltime(timestamp)


#####################################
# LAYOUT DATA + RENDER ENTRYPOINT
#####################################


class ProjectLayoutData(NamedTuple):
    request: Any
    active_projects: "list[Project]"
    project: "Project"
    bookmarks: "list[ProjectBookmark]"


def gen_render_data() -> dict:
    data = load_project_data_from_json(data_json)

    users = data.pop("users")
    user = users[0]

    bookmarks: "list[ProjectBookmark]" = [
        {
            "id": 82,
            "project": data["project"],
            "text": "Test bookmark",
            "url": "http://localhost:8000/bookmarks/9/create",
            "attachment": None,
        },
    ]

    request = make_request(user)

    data["layout_data"] = ProjectLayoutData(
        bookmarks=bookmarks,
        project=data["project"],
        active_projects=[data["project"]],
        request=request,
    )

    return data


def render(data: dict) -> str:
    return str(ProjectPage(**data))


#####################################
#
# COMPONENTS
#
#####################################


# ----- Button -----


class Button(Component):
    citry = app
    name = "Button"

    class Kwargs:
        href: str | None = None
        link: bool | None = None
        disabled: bool | None = False
        variant: ThemeVariant | Literal["plain"] = "primary"
        color: ThemeColor | str = "default"
        type: str | None = "button"
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        common_css = (
            "inline-flex w-full text-sm font-semibold"
            " sm:mt-0 sm:w-auto focus-visible:outline-2 focus-visible:outline-offset-2"
        )
        if kwargs.variant == "plain":
            all_css_class = common_css
        else:
            button_classes = get_styling_css(kwargs.variant, kwargs.color, kwargs.disabled)
            all_css_class = f"{button_classes} {common_css} px-3 py-2 justify-center rounded-md shadow-sm"

        is_link = not kwargs.disabled and (kwargs.href or kwargs.link)
        all_attrs = {**(kwargs.attrs or {})}
        if kwargs.disabled:
            all_attrs["aria-disabled"] = "true"

        return {
            "href": kwargs.href,
            "disabled": kwargs.disabled,
            "type": kwargs.type,
            "btn_class": all_css_class,
            "attrs": all_attrs,
            "is_link": is_link,
        }

    # The body-receiving slot is the default slot (DJC's `{% slot "content"
    # default %}`); citry's default slot is the one named "default", so callers
    # fill it with plain `<c-Button>text</c-Button>` body content.
    template = """
        <a c-if="is_link" c-href="href" c-bind="attrs" c-class="btn_class" class="no-underline"
        ><c-slot /></a>
        <button c-else c-type="type" c-disabled="disabled" c-bind="attrs" c-class="btn_class"
        ><c-slot /></button>
    """


# ----- Icon + HeroIcon -----

# Single hard-coded icon (the benchmark only ever renders this one).
ICONS = {
    "outline": {
        "academic-cap": [
            {
                "stroke-linecap": "round",
                "stroke-linejoin": "round",
                "d": "M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342M6.75 15a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm0 0v-3.675A55.378 55.378 0 0 1 12 8.443m-7.007 11.55A5.981 5.981 0 0 0 6.75 15.75v-1.5",  # noqa: E501
            },
        ],
    },
}


class ComponentDefaultsMeta(type):
    def __new__(mcs, name: str, bases: tuple, namespace: dict) -> type:
        return dataclass(super().__new__(mcs, name, bases, namespace))  # type: ignore[arg-type]


class ComponentDefaults(metaclass=ComponentDefaultsMeta):
    def __post_init__(self) -> None:
        fields = self.__class__.__dataclass_fields__  # type: ignore[attr-defined]
        for field_name, dataclass_field in fields.items():
            if dataclass_field.default is not MISSING and getattr(self, field_name) is None:
                setattr(self, field_name, dataclass_field.default)


class IconDefaults(ComponentDefaults):
    name: str
    variant: str = "outline"
    size: int = 24
    color: str = "currentColor"
    stroke_width: float = 1.5
    viewbox: str = "0 0 24 24"
    attrs: "dict | None" = None


class Icon(Component):
    citry = app
    name = "Icon"

    class Kwargs:
        name: str
        variant: str | None = None
        size: int | None = None
        stroke_width: float | None = None
        viewbox: str | None = None
        svg_attrs: dict | None = None
        color: str | None = ""
        icon_color: str | None = ""
        text_color: str | None = ""
        href: str | None = None
        text_attrs: dict | None = None
        link_attrs: dict | None = None
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        color = kwargs.color or ""
        icon_color = kwargs.icon_color or color
        text_color = kwargs.text_color or color

        svg_attrs = dict(kwargs.svg_attrs or {})
        svg_attrs["class"] = (svg_attrs.get("class") or "") + f" {icon_color or ''} h-6 w-6 shrink-0"

        return {
            "name": kwargs.name,
            "variant": kwargs.variant,
            "size": kwargs.size,
            "viewbox": kwargs.viewbox,
            "stroke_width": kwargs.stroke_width,
            "svg_attrs": svg_attrs,
            "text_color": text_color,
            "text_attrs": kwargs.text_attrs,
            "link_attrs": kwargs.link_attrs,
            "href": kwargs.href,
            "attrs": kwargs.attrs,
        }

    template = """
        <div c-bind="attrs">
            <a c-if="href" c-href="href" c-bind="link_attrs" c-bind="text_attrs" c-class="text_color"
               class="group flex gap-x-3 rounded-md text-sm leading-6 font-semibold">
                <c-heroicons c-name="name" c-variant="variant" c-size="size" c-viewbox="viewbox"
                    c-stroke_width="stroke_width" c-attrs="svg_attrs" /><c-slot />
            </a>
            <span c-else c-bind="text_attrs" c-class="text_color"
                  class="group flex gap-x-3 rounded-md text-sm leading-6 font-semibold">
                <c-heroicons c-name="name" c-variant="variant" c-size="size" c-viewbox="viewbox"
                    c-stroke_width="stroke_width" c-attrs="svg_attrs" /><c-slot />
            </span>
        </div>
    """


class HeroIcon(Component):
    citry = app
    name = "heroicons"

    class Kwargs:
        name: str
        variant: str | None = None
        size: int | None = None
        color: str | None = None
        stroke_width: float | None = None
        viewbox: str | None = None
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        # IconDefaults applies the real defaults where a value is None (DJC's
        # ComponentDefaults), so the Kwargs above mirror DJC's all-None signature.
        kw = IconDefaults(
            name=kwargs.name,
            variant=kwargs.variant,
            size=kwargs.size,
            color=kwargs.color,
            stroke_width=kwargs.stroke_width,
            viewbox=kwargs.viewbox,
            attrs=kwargs.attrs,
        )

        if kw.variant not in ("outline", "solid"):
            msg = f"Invalid variant: {kw.variant}. Must be either 'outline' or 'solid'"
            raise ValueError(msg)

        variant_icons = ICONS["outline"]
        icon_name = "academic-cap"
        icon_paths = variant_icons[icon_name]

        default_attrs: dict[str, Any] = {
            "viewBox": kw.viewbox,
            "style": f"width: {kw.size}px; height: {kw.size}px",
            "aria-hidden": "true",
        }
        if kw.variant == "outline":
            default_attrs["fill"] = "none"
            default_attrs["stroke"] = kw.color
            default_attrs["stroke-width"] = kw.stroke_width
        else:
            default_attrs["fill"] = kw.color
            default_attrs["stroke"] = "none"

        return {"icon_paths": icon_paths, "default_attrs": default_attrs, "attrs": kw.attrs}

    template = """
        <svg c-bind="default_attrs" c-bind="attrs">
            <path c-for="path_attrs in icon_paths" c-bind="path_attrs" />
        </svg>
    """


# ----- Menu + MenuList -----

MaybeNestedList: TypeAlias = list
MenuItemGroup: TypeAlias = list


@dataclass(frozen=True)
class MenuItem:
    value: Any
    link: "str | None" = None
    item_attrs: "dict | None" = None


class Menu(Component):
    citry = app
    name = "Menu"

    class Kwargs:
        items: MaybeNestedList
        model: str | None = None
        attrs: dict | None = None
        activator_attrs: dict | None = None
        list_attrs: dict | None = None
        close_on_esc: bool | None = True
        close_on_click_outside: bool | None = True
        anchor: str | None = None
        anchor_dir: str | None = "bottom"

    def template_data(self, kwargs, slots=None):
        model = kwargs.model
        is_model_overriden = bool(model)
        model = model or "open"
        close_on_click_outside = kwargs.close_on_click_outside
        close_on_esc = kwargs.close_on_esc
        anchor = kwargs.anchor

        all_list_attrs: dict = {}
        if kwargs.list_attrs:
            all_list_attrs.update(kwargs.list_attrs)
        if anchor:
            all_list_attrs[f"x-anchor.{kwargs.anchor_dir}"] = anchor
        all_list_attrs.update({"x-show": model, "x-cloak": ""})

        # The Alpine x-data object, with the same interpolated values DJC built
        # with the `|alpine` filter, assembled here (V3 has no template filters).
        x_data_lines = [
            "{",
            f"'isModelOverriden': {to_alpine_json(is_model_overriden)},",
            f"'modelName': {to_alpine_json(model)},",
            f"'closeOnClickOutside': {to_alpine_json(close_on_click_outside)},",
        ]
        if not is_model_overriden:
            x_data_lines.append(f"'{model}': false,")
        x_data_lines.append(
            "onClickOutside(event) { if (this.closeOnClickOutside) {"
            " if (!this.isModelOverriden) { this[this.modelName] = false; }"
            " $dispatch('click_outside', { origEvent: event }); } }, }"
        )
        root_attrs = {"x-data": " ".join(x_data_lines)}
        if close_on_esc:
            root_attrs["@keydown.escape"] = f"{model} = false"

        activator_attrs = {
            "@click": f"{model} = !{model}",
            "@keydown.enter": f"{model} = !{model}",
            "tabindex": "0",
            "aria-haspopup": "true",
            ":aria-expanded": f"!!{model}",
            "x-ref": "activator",
            **(kwargs.activator_attrs or {}),
        }
        has_activator = bool(self.raw_slots.get("activator") or self.raw_slots.get("default"))

        return {
            "items": kwargs.items,
            "list_attrs": all_list_attrs,
            "attrs": kwargs.attrs,
            "root_attrs": root_attrs,
            "activator_attrs": activator_attrs,
            "has_activator": has_activator,
        }

    template = """
        <div c-bind="attrs" c-bind="root_attrs">
            <div c-if="has_activator" c-bind="activator_attrs"><c-slot name="activator" /></div>
            <c-MenuList c-items="items" c-attrs="list_attrs" />
        </div>
    """


def _normalize_item(item):
    return item if isinstance(item, MenuItem) else MenuItem(value=item)


def _normalize_items_to_groups(items):
    def is_group(item):
        return isinstance(item, Iterable) and not isinstance(item, str)

    groups: list = []
    curr_group = None
    for index, item_or_grp in enumerate(items):
        if isinstance(item_or_grp, Iterable) and not isinstance(item_or_grp, str):
            group = item_or_grp
        else:
            group = curr_group if curr_group is not None else []
            if curr_group is None:
                curr_group = group
            group.append(item_or_grp)
            is_not_last = index < len(items) - 1
            if is_not_last and not is_group(items[index + 1]):
                continue
        groups.append(group)
        curr_group = None
    return groups


def prepare_menu_items(items):
    return [list(map(_normalize_item, group)) for group in _normalize_items_to_groups(items)]


class MenuList(Component):
    citry = app
    name = "MenuList"

    class Kwargs:
        items: MaybeNestedList
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        return {
            "item_groups": prepare_menu_items(kwargs.items),
            "attrs": kwargs.attrs,
        }

    template = """
        <div role="menu" aria-orientation="vertical" c-bind="attrs"
             c-class="'mt-2 divide-y divide-gray-300 rounded-md bg-white shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none'">
            <div c-for="group in item_groups" class="py-1" role="group">
                <c-for each="item in group">
                    <a c-if="item.link" role="menuitem" tabindex="0" c-href="item.link"
                       c-bind="item.item_attrs" c-class="'block'">{{ item.value }}</a>
                    <div c-else role="menuitem" tabindex="0" c-bind="item.item_attrs">{{ item.value }}</div>
                </c-for>
            </div>
        </div>
    """


# ----- Table -----


class TableHeader(NamedTuple):
    name: str
    key: str
    hidden: "bool | None" = None
    cell_attrs: "dict | None" = None


@dataclass(frozen=True)
class TableCell:
    value: Any
    colspan: int = 1
    link: "str | None" = None
    link_attrs: "dict | None" = None
    cell_attrs: "dict | None" = None
    linebreaks: "bool | None" = None


NULL_CELL = TableCell("")


@dataclass(frozen=True)
class TableRow:
    cols: dict = field(default_factory=dict)
    row_attrs: "dict | None" = None
    col_attrs: "dict | None" = None


def create_table_row(cols=None, row_attrs=None, col_attrs=None):
    resolved_cols: dict = {}
    if cols:
        for key, val in cols.items():
            resolved_cols[key] = val if isinstance(val, TableCell) else TableCell(value=val)
    return TableRow(cols=resolved_cols, row_attrs=row_attrs, col_attrs=col_attrs)


def prepare_row_headers(row, headers):
    final_row_headers = []
    headers_to_skip = 0
    for header in headers:
        if headers_to_skip > 0:
            headers_to_skip -= 1
            continue
        final_row_headers.append(header)
        cell = row.cols.get(header.key)
        if cell is not None:
            headers_to_skip = cell.colspan - 1
    return final_row_headers


class Table(Component):
    citry = app
    name = "Table"

    class Kwargs:
        headers: list
        rows: list
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        headers = kwargs.headers
        headers_with_first = [(h, i == 0) for i, h in enumerate(headers)]

        rows_out = []
        for row in kwargs.rows:
            cells = []
            for header in prepare_row_headers(row, headers):
                cell = row.cols.get(header.key)
                cell = NULL_CELL if cell is None else cell
                display = SafeString(linebreaksbr(cell.value)) if cell.linebreaks else cell.value
                cells.append((cell, display))
            rows_out.append((row, cells))

        return {
            "headers_with_first": headers_with_first,
            "rows_out": rows_out,
            "attrs": kwargs.attrs,
        }

    template = """
        <div c-bind="attrs" c-class="'flow-root'">
            <div class="-mx-4 -my-2 overflow-x-auto sm:-mx-6 lg:-mx-8">
                <div class="inline-block min-w-full py-2 align-middle sm:px-6 lg:px-8">
                    <table class="min-w-full divide-y divide-gray-300">
                        <thead>
                            <tr>
                                <th c-for="h, first in headers_with_first" scope="col" c-bind="h.cell_attrs"
                                    c-class="['text-left text-sm font-semibold text-gray-900 py-3.5', 'pl-4 pr-3 sm:pl-0' if first else 'px-3']">
                                    <c-if cond="h.hidden"><span class="sr-only">{{ h.name }}</span></c-if><c-else>{{ h.name }}</c-else>
                                </th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-gray-200">
                            <tr c-for="row, cells in rows_out" c-bind="row.row_attrs">
                                <td c-for="cell, display in cells" c-colspan="cell.colspan"
                                    c-bind="cell.cell_attrs" c-bind="row.col_attrs">
                                    <c-if cond="cell.link"><a c-href="cell.link" c-bind="cell.link_attrs">{{ display }}</a></c-if><c-else>{{ display }}</c-else>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    """


# ----- ExpansionPanel -----


class ExpansionPanel(Component):
    citry = app
    name = "ExpansionPanel"

    js = """
        document.addEventListener("alpine:init", () => {
            Alpine.data("expansion_panel", () => ({
                isOpen: false,
                init() {
                    const initData = JSON.parse(this.$el.dataset.init);
                    this.isOpen = initData.open;
                    const panelId = this.$el.dataset.panelid;
                    const panel = new URL(location.href).searchParams.get("panel");
                    if (panel && panel == panelId) {
                        this.isOpen = true;
                        this.$el.scrollIntoView();
                    }
                },
                togglePanel(event) { this.isOpen = !this.isOpen; },
            }));
        });
    """

    class Kwargs:
        open: bool | None = False
        panel_id: str | None = None
        attrs: dict | None = None
        header_attrs: dict | None = None
        content_attrs: dict | None = None
        icon_position: Literal["left", "right"] = "left"

    def template_data(self, kwargs, slots=None):
        return {
            "attrs": kwargs.attrs,
            "header_attrs": kwargs.header_attrs,
            "content_attrs": kwargs.content_attrs,
            "icon_position": kwargs.icon_position,
            "init_data_json": to_json({"open": kwargs.open}),
            "panel_id": kwargs.panel_id or False,
            # The DJC `attrs:style` / `attrs::class` nested html_attrs syntax,
            # passed to the Icon's `attrs` kwarg as a plain dict here.
            "icon_attrs": {"style": "width: fit-content;", ":class": "{ 'rotate-180': isOpen }"},
        }

    template = """
        <div x-data="expansion_panel" c-data-init="init_data_json" c-bind="attrs" c-data-panelid="panel_id">
            <div @click="togglePanel" c-bind="header_attrs" c-class="'pb-2 cursor-pointer'">
                <c-if cond="icon_position == 'left'"><c-Icon name="chevron-down" variant="outline" c-attrs="icon_attrs" /></c-if>
                <c-slot name="header" />
                <c-if cond="icon_position == 'right'"><c-Icon name="chevron-down" variant="outline" c-attrs="icon_attrs" /></c-if>
            </div>
            <div x-show="isOpen" c-bind="content_attrs"><c-slot name="content" /></div>
        </div>
    """


# ----- Dialog -----


def construct_btn_onclick(model: str, btn_on_click: "str | None") -> Any:
    on_click_cb = f"{model} = false;"
    if btn_on_click:
        on_click_cb = f"{btn_on_click}; {on_click_cb}"
    return SafeString(on_click_cb)


class Dialog(Component):
    citry = app
    name = "Dialog"

    class Kwargs:
        model: str | None = None
        attrs: dict | None = None
        activator_attrs: dict | None = None
        title_attrs: dict | None = None
        content_attrs: dict | None = None
        confirm_hide: bool | None = None
        confirm_text: str | None = "Confirm"
        confirm_href: str | None = None
        confirm_disabled: bool | None = None
        confirm_variant: ThemeVariant | None = "primary"
        confirm_color: ThemeColor | None = None
        confirm_type: str | None = None
        confirm_on_click: str | None = ""
        confirm_attrs: dict | None = None
        cancel_hide: bool | None = None
        cancel_text: str | None = "Cancel"
        cancel_href: str | None = None
        cancel_disabled: bool | None = None
        cancel_variant: ThemeVariant | None = "secondary"
        cancel_color: ThemeColor | None = None
        cancel_type: str | None = None
        cancel_on_click: str | None = ""
        cancel_attrs: dict | None = None
        close_on_esc: bool | None = True
        close_on_click_outside: bool | None = True

    def template_data(self, kwargs, slots=None):
        model = kwargs.model
        is_model_overriden = bool(model)
        model = model or "open"

        cancel_attrs = {**(kwargs.cancel_attrs or {}), "@click": construct_btn_onclick(model, kwargs.cancel_on_click)}
        confirm_attrs = {**(kwargs.confirm_attrs or {}), "@click": construct_btn_onclick(model, kwargs.confirm_on_click)}

        x_data = "{ id: $id('modal-title'), " + (f"'{model}': false, " if not is_model_overriden else "") + "}"
        root_attrs = {"x-data": x_data}
        if kwargs.close_on_esc:
            root_attrs["@keydown.escape"] = f"{model} = false"

        panel_attrs = {}
        if kwargs.close_on_click_outside:
            panel_attrs["@click.away"] = f"{model} = false"

        return {
            "model": model,
            "attrs": kwargs.attrs,
            "activator_attrs": {"@click": f"{model} = true", **(kwargs.activator_attrs or {})},
            "content_attrs": kwargs.content_attrs,
            "title_attrs": kwargs.title_attrs,
            "root_attrs": root_attrs,
            "backdrop_attrs": {"x-show": model},
            "panel_attrs": panel_attrs,
            "confirm_hide": kwargs.confirm_hide,
            "confirm_text": kwargs.confirm_text,
            "confirm_href": kwargs.confirm_href,
            "confirm_disabled": kwargs.confirm_disabled,
            "confirm_variant": kwargs.confirm_variant,
            "confirm_color": kwargs.confirm_color,
            "confirm_type": kwargs.confirm_type,
            "confirm_attrs": confirm_attrs,
            "cancel_hide": kwargs.cancel_hide,
            "cancel_text": kwargs.cancel_text,
            "cancel_href": kwargs.cancel_href,
            "cancel_disabled": kwargs.cancel_disabled,
            "cancel_variant": kwargs.cancel_variant,
            "cancel_color": kwargs.cancel_color,
            "cancel_type": kwargs.cancel_type,
            "cancel_attrs": cancel_attrs,
            "has_activator": bool(self.raw_slots.get("activator") or self.raw_slots.get("default")),
            "has_title": bool(self.raw_slots.get("title")),
        }

    template = """
        <div c-bind="root_attrs" c-bind="attrs">
            <div c-if="has_activator" c-bind="activator_attrs"><c-slot name="activator" /></div>
            <div class="relative z-50" :aria-labelledby="id" role="dialog" aria-modal="true" x-cloak>
                <div class="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" c-bind="backdrop_attrs"></div>
                <div class="fixed inset-0 z-50 w-screen overflow-y-auto" c-bind="backdrop_attrs">
                    <div class="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
                        <div class="relative transform overflow-hidden rounded-lg bg-white text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg" c-bind="panel_attrs">
                            <div class="bg-white px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
                                <div class="sm:flex sm:items-start">
                                    <c-slot name="prepend" />
                                    <div c-bind="content_attrs">
                                        <h3 c-if="has_title" :id="id" c-bind="title_attrs" c-class="'font-semibold text-gray-900'"><c-slot name="title" /></h3>
                                        <c-slot name="content" />
                                    </div>
                                    <c-slot name="append" />
                                </div>
                            </div>
                            <div class="bg-gray-50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6 gap-5">
                                <c-Button c-if="not confirm_hide" c-variant="confirm_variant" c-color="confirm_color" c-disabled="confirm_disabled" c-href="confirm_href" c-type="confirm_type" c-attrs="confirm_attrs">{{ confirm_text }}</c-Button>
                                <c-Button c-if="not cancel_hide" c-variant="cancel_variant" c-color="cancel_color" c-disabled="cancel_disabled" c-href="cancel_href" c-type="cancel_type" c-attrs="cancel_attrs">{{ cancel_text }}</c-Button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    """


# ----- Tags -----


class TagEntry(NamedTuple):
    tag: str
    selected: bool = False


class Tags(Component):
    citry = app
    name = "Tags"

    class Kwargs:
        tag_type: str
        js_props: dict
        editable: bool = True
        max_width: int | str = "300px"
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        # `.upper()` forwards through a string or a Const-wrapped string (and a
        # StrEnum), and the StrEnum keys hash equal to their string value.
        all_tags = TAG_TYPE_META[kwargs.tag_type.upper()].allowed_values
        js_props = kwargs.js_props

        x_props = (
            "{ initAllTags: '" + to_json(all_tags) + "',"
            " initTags: " + str(js_props.get("initTags", "[]")) + ","
            " onChange: " + str(js_props.get("onChange", "() => {}")) + ", }"
        )
        return {
            "editable": kwargs.editable,
            "max_width": kwargs.max_width,
            "attrs": kwargs.attrs,
            "x_props": x_props,
            "remove_btn_attrs": {"class": "!py-1", "@click": "removeTag(index)"},
            "add_btn_attrs": {"class": "!py-1", "@click": "addTag"},
            "has_title": bool(self.raw_slots.get("title")),
        }

    # The `<template x-for>` blocks are client-side Alpine templates, kept as
    # literal elements (citry renders them once; Alpine clones them in the
    # browser). Only the server-evaluated bits use citry directives.
    template = """
        <div x-data="tags" c-x-props="x_props" c-bind="attrs"
             c-class="'pt-3 flex flex-col gap-y-3 items-start'">
            <input x-ref="tagsInput" type="hidden" name="tags" value="" />
            <c-slot name="title"><p class="text-sm">Tags:</p></c-slot>
            <template x-for="(tag, index) in tags.value">
                <div class="tag text-sm flex flex-col gap-1 w-full" c-style="{'max-width': max_width}">
                    <div class="flex gap-6 w-full justify-between items-center">
                        <select name="_tags" class="flex-auto py-1 px-2" @change="(ev) => setTag(index, ev.target.value)" c-disabled="not editable">
                            <template x-for="option in tag.options">
                                <option :value="option" :selected="option === tag.value" x-text="option"></option>
                            </template>
                        </select>
                        <div c-if="editable">
                            <c-Button color="error" c-attrs="remove_btn_attrs">Remove</c-Button>
                        </div>
                    </div>
                </div>
            </template>
            <div c-if="editable" x-show="tags.value.length < allTags.value.length">
                <c-Button c-attrs="add_btn_attrs">Add tag</c-Button>
            </div>
        </div>
    """


# ----- Breadcrumbs -----


@dataclass(frozen=True)
class Breadcrumb:
    value: Any
    link: "str | None" = None
    item_attrs: "dict | None" = None


class Breadcrumbs(Component):
    citry = app
    name = "Breadcrumbs"

    class Kwargs:
        items: list
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        return {
            "items_with_first": [(c, i == 0) for i, c in enumerate(kwargs.items)],
            "attrs": kwargs.attrs,
        }

    template = """
        <nav aria-label="Breadcrumb" c-bind="attrs" c-class="'flex border-b border-gray-200 bg-white'">
            <ol role="list" class="mx-auto flex w-full max-w-screen-xl space-x-4 px-4 sm:px-6 lg:px-8">
                <li c-for="crumb, first in items_with_first" class="flex">
                    <div class="flex items-center">
                        <svg c-if="not first" class="h-full w-6 flex-shrink-0 text-gray-200" viewBox="0 0 24 44"
                             preserveAspectRatio="none" fill="currentColor" aria-hidden="true">
                            <path d="M.293 0l22 22-22 22h1.414l22-22-22-22H.293z" />
                        </svg>
                        <a c-if="crumb.link" c-href="crumb.link" c-bind="crumb.item_attrs"
                           c-class="'ml-4 text-sm font-medium text-gray-500 hover:text-gray-700'">{{ crumb.value }}</a>
                        <span c-else c-bind="crumb.item_attrs"
                              c-class="'ml-4 text-sm font-medium text-gray-500 hover:text-gray-700'">{{ crumb.value }}</span>
                    </div>
                </li>
            </ol>
        </nav>
    """


# ----- ListComponent -----


@dataclass(frozen=True)
class ListItem:
    value: Any
    link: "str | None" = None
    attrs: "dict | None" = None
    meta: "dict | None" = None


class ListComponent(Component):
    citry = app
    name = "List"

    class Kwargs:
        items: list
        attrs: dict | None = None
        item_attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        return {
            "items": kwargs.items,
            "attrs": kwargs.attrs,
            "item_attrs": kwargs.item_attrs,
        }

    template = """
        <ul role="list" c-bind="attrs" c-class="'flex flex-col gap-4'">
            <li c-for="item in items" c-bind="item.attrs" c-bind="item_attrs"
                c-class="'group flex justify-between gap-x-6 border border-gray-300 pl-4 pr-6 bg-white'">
                <div class="flex min-w-0 w-full gap-x-4">
                    <div class="min-w-0 flex-auto">
                        <a c-if="item.link" c-href="item.link"><p class="text-sm font-semibold leading-6 text-gray-900 hover:text-gray-500">{{ item.value }}</p></a>
                        <p c-else class="text-sm font-semibold leading-6 text-gray-900 hover:text-gray-500">{{ item.value }}</p>
                    </div>
                </div>
            </li>
            <c-empty><c-slot name="empty" /></c-empty>
        </ul>
    """


# ----- Bookmarks + Bookmark -----


class BookmarkItem(NamedTuple):
    id: int
    text: str
    url: str
    edit_url: str


class ProjectPageTabsToQueryParams(Enum):
    PROJECT_INFO = {"tabs-proj-right": "1"}
    OUTPUTS = {"tabs-proj-right": "5"}


_bookmark_item_class = "px-4 py-1 text-sm text-gray-900 hover:bg-gray-100 cursor-pointer"
bookmark_menu_items = [
    [MenuItem(value="Edit", link="#", item_attrs={"class": _bookmark_item_class, ":href": "contextMenuItem.value.edit_url"})],
]


class Bookmarks(Component):
    citry = app
    name = "Bookmarks"

    js = """
        document.addEventListener('alpine:init', () => {
            AlpineComposition.registerComponent(Alpine, AlpineComposition.defineComponent({
                name: "bookmarks", props: {}, emits: {},
                setup(props, vm, reactivity) {
                    const { ref } = reactivity;
                    const contextMenuItem = ref(null);
                    const contextMenuRef = ref(null);
                    const onContextMenuToggle = (data) => {
                        const { item, el } = data;
                        const willUntoggle = contextMenuItem.value && contextMenuItem.value.id === item.id;
                        contextMenuItem.value = null; contextMenuRef.value = null;
                        if (willUntoggle) return;
                        setTimeout(() => { contextMenuItem.value = item; contextMenuRef.value = el; });
                    };
                    const onContextMenuClickOutside = () => { contextMenuItem.value = null; contextMenuRef.value = null; };
                    return { contextMenuItem, contextMenuRef, onContextMenuToggle, onContextMenuClickOutside };
                },
            }));
        });
    """

    class Kwargs:
        project_id: int
        bookmarks: list
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        project_id = kwargs.project_id
        bookmark_data: list = []
        attachment_data: list = []
        for bookmark in kwargs.bookmarks:
            is_attachment = bookmark["attachment"] is not None
            if is_attachment:
                edit_url = (
                    f"/edit/{project_id}/bookmark/{bookmark['id']}"
                    f"?{ProjectPageTabsToQueryParams.OUTPUTS.value}"
                    f"&panel={bookmark['attachment']['output']['id']}"
                )
            else:
                edit_url = f"/edit/{project_id}/bookmark/{bookmark['id']}"
            entry = BookmarkItem(text=bookmark["text"], url=bookmark["url"], id=bookmark["id"], edit_url=edit_url)
            (attachment_data if is_attachment else bookmark_data).append(entry)

        return {
            "bookmark_data": bookmark_data,
            "attachment_data": attachment_data,
            "create_bookmark_url": f"/create/{project_id}/bookmark",
            "menu_items": bookmark_menu_items,
            "attrs": kwargs.attrs,
            "theme": theme,
            "bookmark_icon_text_attrs": {"class": "py-2 text-sm"},
            "plus_icon_text_attrs": {"class": "px-2 py-1 text-xs"},
            "plus_icon_svg_attrs": {"class": "mt-0.5 ml-1"},
            "menu_list_attrs": {"class": "w-24 ml-8 z-40"},
            "menu_attrs": {"@click_outside": "onContextMenuClickOutside"},
            "bookmark_js": {"onMenuToggle": "onContextMenuToggle"},
        }

    template = """
        <li x-data="bookmarks" c-bind="attrs" c-class="'pt-4'">
            <c-Icon name="bookmark" variant="outline" c-text_attrs="bookmark_icon_text_attrs">Project Bookmarks</c-Icon>
            <ul class="mx-4">
                <c-for each="bookmark in bookmark_data">
                    <c-Bookmark c-bookmark="bookmark" c-js="bookmark_js" />
                </c-for>
                <li>
                    <c-Icon name="plus" variant="outline" size="18" c-href="create_bookmark_url" c-color="theme.sidebar_link"
                        c-text_attrs="plus_icon_text_attrs" c-svg_attrs="plus_icon_svg_attrs">Add New Bookmark</c-Icon>
                </li>
                <div class="border-b border-gray-200 my-2 pt-2 text-sm font-bold">Attachments:</div>
                <c-for each="bookmark in attachment_data">
                    <c-Bookmark c-bookmark="bookmark" c-js="bookmark_js" />
                </c-for>
            </ul>
            <template x-if="contextMenuItem.value">
                <div class="self-center">
                    <c-Menu c-items="menu_items" model="contextMenuItem.value" anchor="contextMenuRef.value"
                        anchor_dir="bottom" c-list_attrs="menu_list_attrs" c-attrs="menu_attrs" />
                </div>
            </template>
        </li>
    """


class Bookmark(Component):
    citry = app
    name = "Bookmark"

    js = """
        document.addEventListener('alpine:init', () => {
            AlpineComposition.registerComponent(Alpine, AlpineComposition.defineComponent({
                name: "bookmark",
                props: { bookmark: { type: Object, required: true } },
                emits: { menuToggle: (obj) => true },
                setup(props, vm) {
                    const onMenuToggle = () => { vm.$emit('menuToggle', { item: props.bookmark, el: vm.$refs.bookmark_menu }); };
                    return { bookmark: props.bookmark, onMenuToggle };
                },
            }));
        });
    """

    class Kwargs:
        bookmark: Any
        js: dict | None = None

    def template_data(self, kwargs, slots=None):
        bookmark = kwargs.bookmark._asdict()
        js = kwargs.js or {}
        x_props = (
            "{ onMenuToggle: " + str(js.get("onMenuToggle", "() => {}")) + ","
            " bookmark: " + to_alpine_json(bookmark) + ", }"
        )
        return {
            "theme": theme,
            "bookmark": bookmark,
            "x_props": x_props,
            "menu_icon_attrs": {"class": "self-center cursor-pointer", "x-ref": "bookmark_menu", "@click": "onMenuToggle"},
            "menu_icon_svg_attrs": {"class": "inline"},
            "menu_icon_text_attrs": {"class": "p-0"},
        }

    template = """
        <li x-data="bookmark" c-x-props="x_props" class="list-disc ml-8">
            <div class="flex">
                <a c-href="bookmark['url']" target="_blank"
                   c-class="['grow px-2 py-1 text-xs font-semibold', theme.sidebar_link]">{{ bookmark['text'] }}</a>
                <c-Icon name="ellipsis-vertical" variant="outline" c-color="theme.sidebar_link"
                    c-svg_attrs="menu_icon_svg_attrs" c-text_attrs="menu_icon_text_attrs" c-attrs="menu_icon_attrs" />
            </div>
        </li>
    """


# ----- Tabs family -----


class TabEntry(NamedTuple):
    header: str
    content: Any
    disabled: bool = False


class TabStaticEntry(NamedTuple):
    header: str
    href: str
    content: str | None
    disabled: bool = False


class _TabsImpl(Component):
    citry = app
    # DJC registers this as "_tabs", but citry component names must start with a
    # letter, and this component is only ever instantiated directly by Tabs
    # (never via a <c-...> tag), so the registered name is arbitrary.
    name = "TabsImpl"

    js = """
        document.addEventListener("alpine:init", () => {
            Alpine.data("tabs", () => ({
                openTab: 1,
                name: null,
                get tabQueryName() { return `tabs-${this.name}`; },
                init() {
                    if (this.$el.dataset['init']) {
                        const { name } = JSON.parse(this.$el.dataset['init']);
                        if (name) {
                            this.name = name;
                            app.query.registerParam(this.tabQueryName,
                                (newVal, oldVal) => this.onTabQueryParamChange(newVal, oldVal));
                        }
                    }
                    const containerEl = this.$refs.container;
                    if (containerEl.scrollTop) { this.$refs.container.scrollTop = 0; }
                },
                setOpenTab(tabIndex) {
                    this.openTab = tabIndex;
                    if (this.name) { app.query.setParams({ [this.tabQueryName]: tabIndex }); }
                },
                onTabQueryParamChange(newValue, oldValue) {
                    if (newValue == null) return;
                    const n = typeof newValue === "number" ? newValue : Number.parseInt(newValue);
                    if (n === this.openTab) return;
                    this.setOpenTab(n);
                },
            }));
        });
    """

    class Kwargs:
        tabs: list
        name: str | None = None
        attrs: dict | None = None
        header_attrs: dict | None = None
        content_attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        header_data = []
        content_data = []
        for i, tab in enumerate(kwargs.tabs, 1):
            header_data.append(
                (
                    tab,
                    {
                        "@click": f"setOpenTab( {i} )",
                        ":class": "{ 'border-b-2 " + theme.tab_active + "': openTab === " + str(i) + " }",
                    },
                    {":class": f"openTab === {i} ? '{theme.tab_text_active}' : '{theme.tab_text_inactive}'"},
                )
            )
            content_data.append((tab, {"x-show": f"openTab === {i}"}))
        return {
            "attrs": kwargs.attrs,
            "header_data": header_data,
            "content_data": content_data,
            "header_attrs": kwargs.header_attrs,
            "content_attrs": kwargs.content_attrs,
            "data_init_json": to_json({"name": kwargs.name}),
        }

    template = """
        <div x-data="tabs" c-data-init="data_init_json" c-bind="attrs" c-class="'flex flex-col'">
            <ul class="flex border-b text-sm">
                <c-for each="tab, li_attrs, a_attrs in header_data">
                    <li c-if="not tab.disabled" c-bind="li_attrs" c-bind="header_attrs">
                        <a href="#" c-bind="a_attrs" class="bg-white inline-block py-2 px-4 font-semibold transition">{{ tab.header }}</a>
                    </li>
                    <li c-else class="mr-1"><p class="text-gray-300 bg-white inline-block py-2 px-4 font-semibold">{{ tab.header }}</p></li>
                </c-for>
            </ul>
            <div class="w-full h-full flex-grow-1 relative overflow-y-scroll" x-ref="container">
                <article class="px-4 pt-5 absolute w-full h-full">
                    <div c-for="tab, show_attrs in content_data" c-bind="show_attrs" c-bind="content_attrs">{{ tab.content }}</div>
                </article>
            </div>
        </div>
    """


class Tabs(Component):
    # An "API" component: it collects nested <c-TabItem> children (which
    # register themselves through provide/inject) and then renders the real
    # _TabsImpl with the collected list. The collection happens in on_render's
    # generator form, after the slot (and its TabItems) have rendered.
    citry = app
    name = "Tabs"

    class Kwargs:
        name: str | None = None
        attrs: dict | None = None
        header_attrs: dict | None = None
        content_attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        tabs: list = []
        self._collected_tabs = tabs
        self._kw = kwargs
        # The provided list is held by reference (provide freezes the wrapper,
        # not the list), so TabItem children append to this very list.
        self.provide("_tab", tabs=tabs, enabled=True)
        return {}

    def on_render(self):
        _result, error = yield
        if error is not None:
            return None
        return _TabsImpl(
            tabs=self._collected_tabs,
            name=self._kw.name,
            attrs=self._kw.attrs,
            header_attrs=self._kw.header_attrs,
            content_attrs=self._kw.content_attrs,
        )

    template = "<c-slot />"


class TabItem(Component):
    citry = app
    name = "TabItem"

    class Kwargs:
        header: str
        disabled: bool = False

    def template_data(self, kwargs, slots=None):
        tab_ctx = self.inject("_tab")
        if not tab_ctx.enabled:
            msg = "Component 'TabItem' must be a direct child of a Tabs component (not nested in another TabItem)."
            raise RuntimeError(msg)
        self._parent_tabs = tab_ctx.tabs
        self._header = kwargs.header
        self._disabled = kwargs.disabled
        # A disabled _tab for any nested TabItem, so nesting is detected.
        self.provide("_tab", tabs=[], enabled=False)
        return {}

    def on_render(self):
        result, error = yield
        if error is not None:
            return None
        content = SafeString(str(result).strip()) if result is not None else SafeString("")
        self._parent_tabs.append(TabEntry(header=self._header, content=content, disabled=self._disabled))
        return None

    template = "<c-slot />"


class TabsStatic(Component):
    citry = app
    name = "TabsStatic"

    class Kwargs:
        tabs: list
        index: int = 0
        hide_body: bool = False
        attrs: dict | None = None
        header_attrs: dict | None = None
        content_attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        tabs = kwargs.tabs
        index = kwargs.index
        tabs_data = []
        for tab_index, tab in enumerate(tabs):
            is_selected = tab_index == index
            styling = {
                "tab": "border-b-2 " + theme.tab_active if is_selected else "",
                "text": theme.tab_text_active if is_selected else theme.tab_text_inactive,
            }
            tabs_data.append((tab, styling))
        return {
            "attrs": kwargs.attrs,
            "tabs_data": tabs_data,
            "header_attrs": kwargs.header_attrs,
            "content_attrs": kwargs.content_attrs,
            "hide_body": kwargs.hide_body,
            "selected_content": tabs[index].content,
        }

    template = """
        <div c-bind="attrs" c-class="'flex flex-col'">
            <ul class="flex border-b mb-5 bg-white">
                <c-for each="tab, styling in tabs_data">
                    <li c-if="not tab.disabled" c-bind="header_attrs" c-class="['border-b-2', styling['tab']]">
                        <a c-href="tab.href" c-bind="header_attrs"
                           c-class="['bg-white inline-block py-2 px-4 font-semibold transition', styling['text']]">{{ tab.header }}</a>
                    </li>
                    <li c-else class="mr-1"><p class="text-gray-300 bg-white inline-block py-2 px-4 font-semibold">{{ tab.header }}</p></li>
                </c-for>
            </ul>
            <div c-if="not hide_body" class="w-full h-full flex-grow-1 relative overflow-y-scroll">
                <article class="px-4 pt-5 absolute w-full h-full">
                    <div c-bind="content_attrs">{{ selected_content }}</div>
                </article>
            </div>
        </div>
    """


# ----- ProjectUserAction -----


class ProjectUserAction(Component):
    citry = app
    name = "ProjectUserAction"

    class Kwargs:
        project_id: int
        role_id: int
        user_name: str

    def template_data(self, kwargs, slots=None):
        role_data = {
            "delete_url": f"/delete/{kwargs.project_id}/{kwargs.role_id}",
            "role_id": kwargs.role_id,
            "user_name": kwargs.user_name,
        }
        return {
            "x_data": "{ role: " + to_alpine_json(role_data) + ", }",
            "icon_svg_attrs": {"class": "inline mb-1"},
            "icon_attrs": {"class": "p-2", "@click.stop": "$dispatch('user_delete', { role })"},
        }

    template = """
        <div c-x-data="x_data">
            <c-Icon name="trash" variant="outline" c-size="18" href="#" color="text-gray-500 hover:text-gray-400"
                c-svg_attrs="icon_svg_attrs" c-attrs="icon_attrs" />
        </div>
    """


# ----- ProjectStatusUpdates -----


def _make_status_update_data(status_update):
    modified_time_str = format_timestamp(datetime.fromisoformat(status_update["modified"]))
    return {
        "timestamp": modified_time_str + " " + status_update["modified_by"]["name"],
        "text": status_update["text"],
        "edit_href": f"/edit/{status_update['project']['id']}/status_update/{status_update['id']}",
    }


class ProjectStatusUpdates(Component):
    citry = app
    name = "ProjectStatusUpdates"

    class Kwargs:
        project_id: int
        status_updates: list
        editable: bool

    def template_data(self, kwargs, slots=None):
        return {
            "create_status_update_url": f"/create/{kwargs.project_id}/status_update",
            "updates_data": [_make_status_update_data(su) for su in kwargs.status_updates],
            "editable": kwargs.editable,
        }

    template = """
        <div class="prose border-b border-neutral-300 pb-8">
            <div class="flex justify-between items-start mb-4">
                <h3 class="mt-0">Status Updates</h3>
                <c-Button c-if="editable" c-href="create_status_update_url">Add status update</c-Button>
            </div>
            <div c-if="updates_data" class="mt-8">
                <div c-for="update in updates_data" class="px-3 py-2" style="border-top: solid 1px lightgrey">
                    <div class="flex justify-between gap-4 pt-2">
                        <span class="prose-sm prose-figure">{{ update['timestamp'] }}</span>
                        <c-Icon c-if="editable" name="pencil-square" variant="outline" c-href="update['edit_href']"
                            color="text-gray-400 hover:text-gray-500" />
                    </div>
                    <p class="my-0 text-gray-900">{{ update['text'] }}</p>
                </div>
            </div>
        </div>
    """


# ----- ProjectUsers (Django form hand-written) -----

roles_table_headers = [
    TableHeader(key="name", name="Name"),
    TableHeader(key="role", name="Role"),
    TableHeader(key="delete", name="", hidden=True),
]


def _render_choice_field(field_name, label, choices):
    """Hand-written replacement for a Django ChoiceField's table row."""
    options = "".join(f'<option value="{escape(value)}">{escape(text)}</option>' for value, text in choices)
    return (
        f'<tr><th><label for="id_{field_name}">{label}:</label></th>'
        f'<td><select name="{field_name}" id="id_{field_name}" required>{options}</select></td></tr>'
    )


class ProjectUsers(Component):
    citry = app
    name = "ProjectUsers"

    js = """
        document.addEventListener('alpine:init', () => {
            Alpine.data('project_users', () => ({
                isDeleteDialogOpen: false,
                role: null,
                onUserDelete(event) {
                    const { role } = event.detail;
                    this.role = role;
                    this.isDeleteDialogOpen = !!role;
                },
            }));
        });
    """

    class Kwargs:
        project_id: int
        roles_with_users: list
        available_roles: list | None
        available_users: list | None
        editable: bool = False

    def template_data(self, kwargs, slots=None):
        project_id = kwargs.project_id
        editable = kwargs.editable

        table_rows = []
        for role in kwargs.roles_with_users:
            user = role["user"]
            # The nested action is a CitryElement; citry renders it in place and
            # its deps bubble to the page (DJC used deps_strategy="ignore").
            delete_action = (
                ProjectUserAction(user_name=user["name"], project_id=project_id, role_id=role["id"])
                if editable
                else ""
            )
            table_rows.append(
                create_table_row(
                    cols={
                        "name": TableCell(user["name"]),
                        "role": TableCell(role["name"]),
                        "delete": TableCell(delete_action),
                    },
                )
            )

        role_choices = [(r, r) for r in kwargs.available_roles] if kwargs.available_roles else []
        user_choices = [(str(u["id"]), u["name"]) for u in kwargs.available_users] if kwargs.available_users else []
        add_user_form = SafeString(
            _render_choice_field("user_id", "User", user_choices) + _render_choice_field("role", "Role", role_choices)
        )

        return {
            "editable": editable,
            "table_headers": roles_table_headers,
            "table_rows": table_rows,
            "add_user_form": add_user_form,
            "submit_url": f"/submit/{project_id}/role/create",
            "project_url": f"/project/{project_id}",
            "table_attrs": {"@user_delete": "onUserDelete"},
            "dialog_confirm_attrs": {":href": "role.delete_url"},
            "dialog_content_attrs": {"class": "w-full"},
            "title_icon_attrs": {"class": "p-2 self-center"},
        }

    template = """
        <div x-data="project_users">
            <c-Table c-if="table_rows" c-headers="table_headers" c-rows="table_rows" c-attrs="table_attrs" />
            <div c-if="editable">
                <h4>Set project roles</h4>
                <form c-hx-post="submit_url" hx-swap="outerHTML" method="post">
                    <table>{{ add_user_form }}</table>
                    <c-Button type="submit">Set role</c-Button>
                    <c-Button variant="secondary" c-href="project_url">Go back</c-Button>
                </form>
                <template x-if="role && isDeleteDialogOpen">
                    <c-Dialog model="isDeleteDialogOpen" confirm_text="Delete" confirm_href="#" confirm_color="error"
                        c-confirm_attrs="dialog_confirm_attrs" c-content_attrs="dialog_content_attrs">
                        <c-fill name="title">
                            <div class="flex">
                                <span>Remove <span x-text="role && role.user_name"></span> from this project?</span>
                                <c-Icon name="trash" variant="outline" c-size="18" c-attrs="title_icon_attrs" />
                            </div>
                        </c-fill>
                        <c-fill name="content"><div>This action cannot be undone.</div></c-fill>
                    </c-Dialog>
                </template>
            </div>
        </div>
    """


# ----- Form (dynamic content tag via <c-element>, feature B) -----


class Form(Component):
    citry = app
    name = "Form"

    js = """
        document.addEventListener('alpine:init', () => {
            Alpine.data('form', () => {
                const data = Alpine.reactive({
                    formData: {}, isSubmitting: false,
                    updateFormModel(event) {
                        const form = this.$el.closest("form");
                        if (!form) { this.formData = null; return; }
                        const formDataObj = new FormData(form);
                        this.formData = [...formDataObj.entries()].reduce((agg, [k, v]) => { agg[k] = v; return agg; }, {});
                    },
                    onSubmit(event) {
                        if (this.isSubmitting) return;
                        this.isSubmitting = true;
                        event.target.submit();
                    },
                });
                Alpine.watch(() => data.formData, (newVal, oldVal) => {
                    if (JSON.stringify(newVal || null) === JSON.stringify(oldVal || null)) return;
                    data.$dispatch('change', newVal);
                });
                return data;
            });
        });
    """

    class Kwargs:
        type: Literal["table", "paragraph", "ul"] | None = None
        editable: bool = True
        method: str = "post"
        submit_hide: bool | None = None
        submit_text: str | None = "Submit"
        submit_href: str | None = None
        submit_disabled: bool | None = None
        submit_variant: ThemeVariant | None = "primary"
        submit_color: ThemeColor | None = None
        submit_type: str | None = "submit"
        submit_attrs: dict | None = None
        cancel_hide: bool | None = None
        cancel_text: str | None = "Cancel"
        cancel_href: str | None = None
        cancel_disabled: bool | None = None
        cancel_variant: ThemeVariant | None = "secondary"
        cancel_color: ThemeColor | None = None
        cancel_type: str | None = "button"
        cancel_attrs: dict | None = None
        actions_hide: bool | None = None
        actions_attrs: dict | None = None
        form_content_attrs: dict | None = None
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        form_content_tag = {"table": "table", "paragraph": "div", "ul": "ul"}.get(kwargs.type, "div")
        form_attrs = {}
        if kwargs.submit_href and kwargs.editable:
            form_attrs["action"] = kwargs.submit_href
        return {
            "form_content_tag": form_content_tag,
            "form_attrs": form_attrs,
            "form_content_attrs": kwargs.form_content_attrs,
            "method": kwargs.method,
            "attrs": kwargs.attrs,
            "actions_hide": kwargs.actions_hide,
            "actions_attrs": kwargs.actions_attrs,
            "submit_hide": kwargs.submit_hide,
            "submit_text": kwargs.submit_text,
            "submit_disabled": kwargs.submit_disabled or not kwargs.editable,
            "submit_variant": kwargs.submit_variant,
            "submit_color": kwargs.submit_color,
            "submit_type": kwargs.submit_type,
            "submit_attrs": {**(kwargs.submit_attrs or {}), ":disabled": "isSubmitting"},
            "cancel_hide": kwargs.cancel_hide,
            "cancel_text": kwargs.cancel_text,
            "cancel_href": kwargs.cancel_href,
            "cancel_disabled": kwargs.cancel_disabled,
            "cancel_variant": kwargs.cancel_variant,
            "cancel_color": kwargs.cancel_color,
            "cancel_type": kwargs.cancel_type,
            "cancel_attrs": kwargs.cancel_attrs,
        }

    template = """
        <form c-bind="form_attrs" c-method="method" x-data="form" c-bind="attrs">
            <c-element c-is="form_content_tag" @click="updateFormModel" @change="updateFormModel" c-bind="form_content_attrs">
                <c-slot />
            </c-element>
            <c-slot name="below_form" />
            <div c-if="not actions_hide" c-bind="actions_attrs" c-class="'pt-4'">
                <c-slot name="actions_prepend" />
                <c-Button c-if="not submit_hide" c-variant="submit_variant" c-color="submit_color"
                    c-disabled="submit_disabled" c-type="submit_type" c-attrs="submit_attrs">{{ submit_text }}</c-Button>
                <c-Button c-if="not cancel_hide" c-variant="cancel_variant" c-color="cancel_color"
                    c-disabled="cancel_disabled" c-href="cancel_href" c-type="cancel_type" c-attrs="cancel_attrs">{{ cancel_text }}</c-Button>
                <c-slot name="actions_append" />
            </div>
        </form>
    """


# ----- ProjectOutput data types + ProjectOutputBadge -----

OUTPUT_DESCRIPTION_PLACEHOLDER = "Placeholder text"
FORM_SHORT_TEXT_MAX_LEN = 255


class ProjectInfoEntry(NamedTuple):
    title: str
    value: str


class AttachmentWithTags(NamedTuple):
    attachment: Any
    tags: list


class OutputWithAttachments(NamedTuple):
    output: Any
    attachments: list


class OutputWithAttachmentsAndDeps(NamedTuple):
    output: Any
    attachments: list
    dependencies: list


class RenderedAttachment(NamedTuple):
    url: str
    text: str
    tags: list


class RenderedOutputDep(NamedTuple):
    dependency: Any
    phase_url: str
    attachments: list


class RenderedProjectOutput(NamedTuple):
    output: Any
    dependencies: list
    has_missing_deps: bool
    output_data: dict
    attachments: list
    update_output_url: str


class ProjectOutputBadge(Component):
    citry = app
    name = "ProjectOutputBadge"

    class Kwargs:
        completed: bool
        missing_deps: bool

    def template_data(self, kwargs, slots=None):
        return {
            "completed": kwargs.completed,
            "missing_deps": kwargs.missing_deps,
            "check_interactive": theme.check_interactive,
            "warn_icon_attrs": {"title": "A dependent dependency has not been met!"},
            "check_icon_attrs": {"class": "p-2"},
        }

    template = """
        <span class="flex h-9 items-center">
            <c-Icon c-if="missing_deps" name="exclamation-triangle" variant="outline" color="text-black"
                c-size="32" c-stroke_width="2" c-attrs="warn_icon_attrs" />
            <span c-elif="completed" c-class="['relative z-10 flex h-8 w-8 items-center justify-center rounded-full', check_interactive]">
                <c-Icon name="check" variant="outline" color="text-white" c-size="20" c-stroke_width="2" c-attrs="check_icon_attrs" />
            </span>
            <span c-else class="flex h-9 items-center" aria-hidden="true">
                <span class="relative z-10 flex h-8 w-8 items-center justify-center rounded-full border-2 border-gray-300 bg-white"></span>
            </span>
        </span>
    """


# ----- ProjectOutputAttachments -----


class ProjectOutputAttachments(Component):
    citry = app
    name = "ProjectOutputAttachments"

    js = """
        document.addEventListener("alpine:init", () => {
            AlpineComposition.registerComponent(Alpine, AlpineComposition.defineComponent({
                name: "project_output_attachments",
                props: { attachments: { type: Object, required: true } },
                emits: {
                    updateAttachmentData: (index, data) => true,
                    setAttachmentTags: (index, tags) => true,
                    removeAttachment: (index) => true,
                    toggleAttachment: (index) => true,
                },
                setup(props, vm, { toRefs }) {
                    const { attachments } = toRefs(props);
                    return { attachments };
                },
            }));
        });
    """

    class Kwargs:
        has_attachments: bool
        js_props: dict
        editable: bool
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        return {
            "has_attachments": kwargs.has_attachments,
            "editable": kwargs.editable,
            "attrs": kwargs.attrs,
            "x_props": "{ ..." + serialize_to_js(kwargs.js_props) + ", }",
            "text_max_len": FORM_SHORT_TEXT_MAX_LEN,
            "tag_type": "project_output_attachment",
            "preview_btn_attrs": {
                "x-bind:href": "attachment.url",
                "x-text": "attachment.text",
                "target": "_blank",
                "class": "hover:text-gray-600 !underline",
                "style": "color: cornflowerblue;",
            },
            "edit_btn_attrs": {"class": "!py-1", "x-text": "attachment.isPreview ? 'Edit' : 'Preview'", "@click": "() => $emit('toggleAttachment', index)"},
            "remove_btn_attrs": {"class": "!py-1", "@click": "() => $emit('removeAttachment', index)"},
            "tags_js_props": {"initTags": "attachment.tags", "onChange": "(tags) => $emit('setAttachmentTags', index, tags)"},
            "tags_attrs": {"class": "pb-8"},
        }

    template = """
        <div x-data="project_output_attachments" c-x-props="x_props" c-bind="attrs"
             c-class="'pt-3 flex flex-col gap-y-3 items-start'">
            <div>
                <c-if cond="not has_attachments and editable">This output does not have any attachments, create one below:</c-if>
                <c-elif cond="not has_attachments and not editable">This output does not have any attachments.</c-elif>
                <c-elif cond="has_attachments and not editable">Attachments:</c-elif>
                <c-else></c-else>
            </div>
            <template x-for="(attachment, index) in attachments.value">
                <div class="project-output-form-attachment w-full">
                    <div class="text-sm flex gap-3 w-full justify-between">
                        <div x-show="attachment.isPreview">
                            <c-Button variant="plain" c-link="True" c-attrs="preview_btn_attrs" />
                        </div>
                        <div x-show="!attachment.isPreview" class="flex flex-col gap-1">
                            <label for="id_text">Text:</label>
                            <input type="text" name="text" id="id_text" c-maxlength="text_max_len" required
                                c-disabled="not editable" class="text-sm py-1 px-2" :value="attachment.text"
                                @change="(ev) => $emit('updateAttachmentData', index, { text: ev.target.value })" />
                            <label for="id_url">Url:</label>
                            <input type="url" name="url" id="id_url" required c-disabled="not editable"
                                class="text-sm py-1 px-2" :value="attachment.url"
                                @change="(ev) => $emit('updateAttachmentData', index, { url: ev.target.value })" />
                        </div>
                        <div c-if="editable" class="flex gap-2 flex-wrap justify-end">
                            <div><c-Button c-attrs="edit_btn_attrs">Edit</c-Button></div>
                            <div><c-Button color="error" c-attrs="remove_btn_attrs">Remove</c-Button></div>
                        </div>
                    </div>
                    <c-Tags c-tag_type="tag_type" c-editable="editable" c-js_props="tags_js_props" c-attrs="tags_attrs" />
                </div>
            </template>
        </div>
    """


# ----- ProjectOutputDependency -----


class ProjectOutputDependency(Component):
    citry = app
    name = "ProjectOutputDependency"

    js = """
        document.addEventListener('alpine:init', () => {
            AlpineComposition.registerComponent(Alpine, AlpineComposition.defineComponent({
                name: 'project_output_dependency',
                props: { initAttachments: { type: String, required: true } },
                setup(props, vm, { ref }) {
                    const attachments = ref([]);
                    if (props.initAttachments) {
                        attachments.value = JSON.parse(props.initAttachments).map(({ url, text, tags }) => ({
                            url, text, tags, isPreview: true,
                        }));
                    }
                    return { attachments };
                },
            }));
        });
    """

    class Kwargs:
        dependency: Any

    def template_data(self, kwargs, slots=None):
        dep = kwargs.dependency  # RenderedOutputDep
        output = dep.dependency.output  # the output dict
        return {
            "attachments": dep.attachments,
            "x_props": "{ initAttachments: '" + to_json(dep.attachments) + "' }",
            "output_completed": output["completed"],
            "output_description": output.get("description"),
            "output_name": output["name"],
            "phase_type_title": title_case(output["phase"]["phase_template"]["type"]),
            "phase_url": dep.phase_url,
            "placeholder": OUTPUT_DESCRIPTION_PLACEHOLDER,
            "warn_icon_attrs": {"class": "float-left pr-1"},
            "phase_btn_attrs": {"target": "_blank", "class": "hover:text-gray-600 !underline"},
        }

    template = """
        <div class="pb-3 mb-3 border-b border-solid border-gray-300" x-data="project_output_dependency" c-x-props="x_props">
            <div class="w-full bg-gray-100 text-sm p-2" style="min-height: 100px;">
                <c-if cond="output_completed">
                    <c-if cond="output_description">{{ output_description }}</c-if>
                    <span c-else class="italic text-gray-500">{{ placeholder }}</span>
                </c-if>
                <span c-else class="text-gray-500 italic">
                    <c-Icon name="exclamation-triangle" variant="outline" c-size="24" c-stroke_width="2"
                        color="text-gray-500" c-attrs="warn_icon_attrs" />
                    Missing '{{ output_name }}' from
                    <c-Button variant="plain" c-href="phase_url" c-attrs="phase_btn_attrs">{{ phase_type_title }}</c-Button>
                </span>
            </div>
            <c-ProjectOutputAttachments c-editable="False" c-has_attachments="attachments"
                c-js_props="{'attachments': 'attachments.value'}" />
        </div>
    """


# ----- ProjectOutputForm -----


class ProjectOutputForm(Component):
    citry = app
    name = "ProjectOutputForm"

    js = """
        document.addEventListener('alpine:init', () => {
            AlpineComposition.registerComponent(Alpine, AlpineComposition.defineComponent({
                name: 'project_output_form',
                props: { initAttachments: { type: String, required: true } },
                setup(props, vm, { ref }) {
                    const attachments = ref([]);
                    if (props.initAttachments) {
                        attachments.value = JSON.parse(props.initAttachments);
                    }
                    return { attachments };
                },
            }));
        });
    """

    class Kwargs:
        data: Any
        editable: bool

    def template_data(self, kwargs, slots=None):
        data = kwargs.data  # RenderedProjectOutput
        return {
            "editable": kwargs.editable,
            "update_output_url": data.update_output_url,
            "output_description": data.output.get("description"),
            "output_completed": data.output["completed"],
            "attachments": data.attachments,
            "x_props": "{ initAttachments: '" + to_json([d._asdict() for d in data.attachments]) + "' }",
            "placeholder": OUTPUT_DESCRIPTION_PLACEHOLDER,
            "add_btn_attrs": {"@click": "addAttachment"},
            "save_btn_attrs": {"@click": "onOutputSubmit({ reload: true })"},
            "attach_js_props": {
                "attachments": "attachments.value",
                "onToggleAttachment": "(index) => toggleAttachmentPreview(index)",
                "onSetAttachmentTags": "(index, tags) => setAttachmentTags(index, tags)",
                "onUpdateAttachmentData": "(index, data) => updateAttachmentData(index, data)",
                "onRemoveAttachment": "(index) => removeAttachment(index)",
            },
        }

    template = """
        <div x-data="project_output_form" c-x-props="x_props">
            <c-Form c-submit_href="update_output_url" c-actions_hide="True">
                <c-if cond="editable">
                    <textarea name="description" class="w-full text-sm p-2 mb-2" c-placeholder="placeholder"
                        style="min-height: 100px;">{{ output_description }}</textarea>
                </c-if>
                <div c-else class="w-full bg-gray-100 italic text-gray-500 text-sm p-2 mb-2" style="min-height: 100px;">
                    <c-if cond="output_description">{{ output_description }}</c-if>
                    <c-else>{{ placeholder }}</c-else>
                </div>
                <div class="flex flex-wrap justify-between items-center gap-y-3">
                    <div class="flex items-center gap-x-2">
                        Completed:
                        <input type="hidden" value="0" name="completed" c-disabled="not editable" />
                        <input type="checkbox" name="completed" style="height: 20px; width: 20px"
                            c-checked="output_completed" c-disabled="not editable" />
                    </div>
                    <div c-if="editable" class="flex gap-x-2 ml-auto items-center justify-between basis-52">
                        <c-Button variant="secondary" c-attrs="add_btn_attrs">Add attachment</c-Button>
                        <c-Button c-attrs="save_btn_attrs">Save</c-Button>
                    </div>
                </div>
                <c-ProjectOutputAttachments c-has_attachments="attachments" c-editable="editable" c-js_props="attach_js_props" />
            </c-Form>
        </div>
    """


# ----- ProjectOutputs -----


class ProjectOutputs(Component):
    citry = app
    name = "ProjectOutputs"

    class Kwargs:
        project_id: int
        phase_type: str
        outputs: list
        editable: bool

    def template_data(self, kwargs, slots=None):
        project_id = kwargs.project_id
        outputs_data = []
        for output, attachments, dependencies in kwargs.outputs:
            attach_data = [RenderedAttachment(url=a[0]["url"], text=a[0]["text"], tags=a[1]) for a in attachments]
            deps = []
            for dep in dependencies:
                dep_output, dep_attachments = dep
                deps.append(
                    RenderedOutputDep(
                        # The raw dep is a (output, attachments) tuple; wrap it so
                        # ProjectOutputDependency can read `.output`/`.attachments`.
                        dependency=OutputWithAttachments(output=dep_output, attachments=dep_attachments),
                        phase_url=f"/phase/{project_id}/{dep_output['phase']['phase_template']['type']}",
                        attachments=[{"url": a[0]["url"], "text": a[0]["text"], "tags": a[1]} for a in dep_attachments],
                    )
                )
            has_missing_deps = any(not o["completed"] for o, _ in dependencies)
            outputs_data.append(
                RenderedProjectOutput(
                    output=output,
                    dependencies=deps,
                    has_missing_deps=has_missing_deps,
                    output_data={"editable": kwargs.editable},
                    attachments=attach_data,
                    update_output_url="/update",
                )
            )
        return {
            "outputs_data": outputs_data,
            "editable": kwargs.editable,
            "panel_attrs": {"class": "border-b border-solid border-gray-300 pb-2 mb-3"},
            "panel_header_attrs": {"class": "flex align-center justify-between"},
        }

    template = """
        <div class="flex flex-col">
            <c-for each="data in outputs_data">
                <div class="flex gap-x-3">
                    <div>
                        <c-ProjectOutputBadge c-completed="data.output['completed']" c-missing_deps="data.has_missing_deps" />
                    </div>
                    <div class="w-full">
                        <c-ExpansionPanel c-panel_id="data.output['id']" icon_position="right"
                            c-attrs="panel_attrs" c-header_attrs="panel_header_attrs">
                            <c-fill name="header"><div>{{ data.output['name'] }}</div></c-fill>
                            <c-fill name="content">
                                <div>
                                    <c-for each="dep in data.dependencies"><c-ProjectOutputDependency c-dependency="dep" /></c-for>
                                    <c-ProjectOutputForm c-data="data" c-editable="editable" />
                                </div>
                            </c-fill>
                        </c-ExpansionPanel>
                    </div>
                </div>
            </c-for>
        </div>
    """


# ----- ProjectOutputsSummary -----


class ProjectOutputsSummary(Component):
    citry = app
    name = "ProjectOutputsSummary"

    class Kwargs:
        project_id: int
        outputs: list
        editable: bool
        phase_titles: dict

    def template_data(self, kwargs, slots=None):
        outputs_by_phase = group_by(kwargs.outputs, lambda output, _: output[0]["phase"]["phase_template"]["type"])
        groups = []
        for phase_meta in PROJECT_PHASES_META.values():
            phase_outputs = outputs_by_phase.get(phase_meta.type, [])
            groups.append(
                {
                    "phase_title": kwargs.phase_titles[phase_meta.type],
                    "phase_type": phase_meta.type,
                    "outputs": phase_outputs,
                    "has_outputs": bool(phase_outputs),
                }
            )
        return {
            "project_id": kwargs.project_id,
            "editable": kwargs.editable,
            "groups": groups,
            "panel_header_attrs": {"class": "flex gap-x-2 prose"},
        }

    template = """
        <div class="flex flex-col gap-y-3">
            <c-for each="group in groups">
                <c-ExpansionPanel c-open="group['has_outputs']" c-header_attrs="panel_header_attrs">
                    <c-fill name="header"><h3 class="m-0">{{ group['phase_title'] }}</h3></c-fill>
                    <c-fill name="content">
                        <c-if cond="group['outputs']">
                            <c-ProjectOutputs c-outputs="group['outputs']" c-project_id="project_id"
                                c-phase_type="group['phase_type']" c-editable="editable" />
                        </c-if>
                        <c-else>No outputs</c-else>
                    </c-fill>
                </c-ExpansionPanel>
            </c-for>
        </div>
    """


# ----- ProjectInfo -----


class ProjectInfo(Component):
    citry = app
    name = "ProjectInfo"

    class Kwargs:
        project: Any
        project_tags: list
        contacts: list
        status_updates: list
        roles_with_users: list
        editable: bool

    def template_data(self, kwargs, slots=None):
        project = kwargs.project
        pid = project["id"]
        contacts_data = [
            {"name": c["name"], "job": c["job"], "link_url": f"/contacts/{c['link_id']}"} for c in kwargs.contacts
        ]
        project_info = [
            ProjectInfoEntry("Org", project["organization"]["name"]),
            ProjectInfoEntry("Duration", f"{project['start_date']} - {project['end_date']}"),
            ProjectInfoEntry("Status", project["status"]),
            ProjectInfoEntry("Tags", ", ".join(kwargs.project_tags) or "-"),
        ]
        return {
            "project_id": pid,
            "project_edit_url": f"/edit/{pid}/",
            "edit_contacts_url": f"/edit/{pid}/contacts/",
            "edit_project_roles_url": f"/edit/{pid}/roles/",
            "contacts_data": contacts_data,
            "roles_with_users": kwargs.roles_with_users,
            "project_info": project_info,
            "status_updates": kwargs.status_updates,
            "editable": kwargs.editable,
            "edit_btn_attrs": {"class": "not-prose"},
        }

    template = """
        <div class="prose flex flex-col gap-8">
            <div class="border-b border-neutral-300">
                <div class="flex justify-between items-start">
                    <h3 class="mt-0">Project Info</h3>
                    <c-Button c-if="editable" c-href="project_edit_url" c-attrs="edit_btn_attrs">Edit Project</c-Button>
                </div>
                <table>
                    <tr c-for="key, value in project_info">
                        <td class="font-bold pr-4">{{ key }}:</td>
                        <td>{{ value }}</td>
                    </tr>
                </table>
            </div>
            <c-ProjectStatusUpdates c-project_id="project_id" c-status_updates="status_updates" c-editable="editable" />
            <div class="xl:grid xl:grid-cols-2 gap-10">
                <div class="border-b border-neutral-300">
                    <div class="flex justify-between items-start">
                        <h3 class="mt-0">Team</h3>
                        <c-Button c-if="editable" c-href="edit_project_roles_url" c-attrs="edit_btn_attrs">Edit Team</c-Button>
                    </div>
                    <c-ProjectUsers c-project_id="project_id" c-roles_with_users="roles_with_users"
                        c-available_roles="None" c-available_users="None" c-editable="False" />
                </div>
                <div>
                    <div class="flex justify-between items-start max-xl:mt-6">
                        <h3 class="mt-0">Contacts</h3>
                        <c-Button c-if="editable" c-href="edit_contacts_url" c-attrs="edit_btn_attrs">Edit Contacts</c-Button>
                    </div>
                    <table c-if="contacts_data">
                        <tr><th>Name</th><th>Job</th><th>Link</th></tr>
                        <tr c-for="row in contacts_data">
                            <td>{{ row['name'] }}</td>
                            <td>{{ row['job'] }}</td>
                            <td><c-Icon c-href="row['link_url']" name="arrow-top-right-on-square" variant="outline"
                                color="text-gray-400 hover:text-gray-500" /></td>
                        </tr>
                    </table>
                    <p c-else class="text-sm italic">No entries</p>
                </div>
            </div>
        </div>
    """


# ----- ProjectNotes -----


def _make_comment_data(note, comment):
    modified_time_str = format_timestamp(datetime.fromisoformat(comment["modified"]))
    return {
        "timestamp": modified_time_str + " " + comment["modified_by"]["name"],
        # DJC stored this under "notes" but its template reads `comment.text`
        # (so it rendered empty); keyed as "text" here so the text renders.
        "text": comment["text"],
        "edit_href": f"/update/{note['project']['id']}/note/{note['id']}/comment/{comment['id']}/",
    }


def _make_notes_data(notes, comments_by_notes):
    notes_data = []
    for note in notes:
        comments = comments_by_notes.get(note["id"], [])
        notes_data.append(
            {
                "text": note["text"],
                "timestamp": note["created"],
                "edit_href": f"/edit/{note['project']['id']}/note/{note['id']}/",
                "comments": [_make_comment_data(note, c) for c in comments],
                "create_comment_url": f"/create/{note['project']['id']}/note/{note['id']}/",
            }
        )
    return notes_data


class ProjectNotes(Component):
    citry = app
    name = "ProjectNotes"

    class Kwargs:
        project_id: int
        notes: list
        comments_by_notes: dict
        editable: bool

    def template_data(self, kwargs, slots=None):
        return {
            "create_note_url": f"/create/{kwargs.project_id}/note/",
            "notes_data": _make_notes_data(kwargs.notes, kwargs.comments_by_notes),
            "editable": kwargs.editable,
        }

    template = """
        <div class="prose">
            <h3>Notes</h3>
            <div c-if="notes_data" class="mt-8">
                <div c-for="note in notes_data" class="py-2" style="border-top: solid 1px lightgrey">
                    <div class="flex justify-between gap-4 pt-2">
                        <span class="prose-sm prose-figure">{{ note['timestamp'] }}</span>
                        <c-Icon c-if="editable" name="pencil-square" variant="outline" c-href="note['edit_href']"
                            color="text-gray-400 hover:text-gray-500" />
                    </div>
                    <p class="my-0 text-gray-900">{{ note['text'] }}</p>
                    <details class="px-8 py-2">
                        <summary class="font-medium">Comments</summary>
                        <div c-for="comment in note['comments']" class="pl-8 pb-2" style="border-top: solid 1px grey;">
                            <div class="flex justify-between gap-4 pt-2">
                                <span class="prose-sm prose-figure">{{ comment['timestamp'] }}</span>
                                <c-Icon c-if="editable" name="pencil-square" variant="outline" c-href="comment['edit_href']"
                                    color="text-gray-400 hover:text-gray-500" />
                            </div>
                            <div class="flex-auto"><p class="my-0">{{ comment['text'] }}</p></div>
                        </div>
                        <div class="text-right">
                            <c-Button c-if="editable" c-href="note['create_comment_url']">Add comment</c-Button>
                        </div>
                    </details>
                </div>
            </div>
            <c-Button c-if="editable" c-href="create_note_url">Add Note</c-Button>
        </div>
    """


# ----- Navbar -----


class Navbar(Component):
    citry = app
    name = "Navbar"

    class Kwargs:
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        return {"attrs": kwargs.attrs}

    template = """
        <div c-bind="attrs"
             c-class="'sticky top-0 z-30 flex h-16 shrink-0 items-center gap-x-4 border-b border-gray-200 bg-white px-4 shadow-sm sm:gap-x-6 sm:px-6 lg:px-8'">
            <button type="button" class="-m-2.5 p-2.5 text-gray-700" @click="$dispatch('sidebar_toggle')">
                <span class="sr-only">Open sidebar</span>
                <c-Icon name="bars-3" variant="outline" />
            </button>
            <div class="h-6 w-px bg-gray-900/10 lg:hidden" aria-hidden="true"></div>
            <div class="flex flex-1 gap-x-4 self-stretch lg:gap-x-6">
                <form class="relative flex flex-1 items-center" action="#" method="GET"></form>
                <div class="flex items-center gap-x-4 lg:gap-x-6">
                    <div class="hidden lg:block lg:h-6 lg:w-px lg:bg-gray-900/10" aria-hidden="true"></div>
                </div>
            </div>
        </div>
    """


# ----- RenderContextProvider + Sidebar -----


class RenderContext(NamedTuple):
    request: Any
    user: Any
    csrf_token: str


class RenderContextProvider(Component):
    citry = app
    name = "RenderContextProvider"

    class Kwargs:
        request: Any

    def template_data(self, kwargs, slots=None):
        context = RenderContext(
            request=kwargs.request,
            user=kwargs.request.user,
            csrf_token=get_csrf_token(kwargs.request),
        )
        self.provide("render_context", render_context=context)
        return {}

    template = "<c-slot />"


class SidebarItem(NamedTuple):
    name: str
    icon: str | None = None
    icon_variant: str | None = None
    href: str | None = None
    children: list | None = None


def gen_sidebar_menu_items(active_projects):
    return [
        SidebarItem(name="Homepage", icon="home", icon_variant="outline", href="/"),
        SidebarItem(
            name="Projects",
            icon="folder",
            icon_variant="outline",
            href="/projects",
            children=[SidebarItem(name=p["name"], icon=None, href=f"/projects/{p['id']}") for p in active_projects],
        ),
        SidebarItem(name="Page 3", icon="folder", icon_variant="outline", href="/page-3"),
        SidebarItem(name="Page 4", icon="bars-arrow-down", icon_variant="outline", href="/page-4"),
        SidebarItem(name="page-5", icon="forward", icon_variant="outline", href="/page-5"),
        SidebarItem(name="FAQ", icon="archive-box", icon_variant="outline", href="/faq"),
    ]


class Sidebar(Component):
    citry = app
    name = "Sidebar"

    class Kwargs:
        active_projects: list
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        user = self.inject("render_context").render_context.user
        is_staff = user.get("is_staff", False) if isinstance(user, dict) else getattr(user, "is_staff", False)
        return {
            "items": gen_sidebar_menu_items(kwargs.active_projects),
            "attrs": kwargs.attrs,
            "is_staff": is_staff,
            "sidebar_class": theme.sidebar,
            "sidebar_link": theme.sidebar_link,
            "faq_url": "/faq",
            "feedback_link_attrs": {"target": "_blank"},
            "icon_text_attrs": {"class": "p-2"},
            "child_btn_attrs": {"class": "p-2 !w-full"},
        }

    template = """
        <div c-bind="attrs" c-class="['flex grow flex-col gap-y-5 overflow-y-auto px-6 pb-4', sidebar_class]">
            <div class="flex h-16 shrink-0 items-center">DEMO</div>
            <nav class="flex flex-1 flex-col">
                <ul role="list" class="flex flex-1 flex-col gap-y-7">
                    <li>
                        <c-slot name="content" />
                        <ul role="list" class="-mx-2 space-y-1">
                            <c-for each="sidebar_item in items">
                                <li>
                                    <c-Icon c-name="sidebar_item.icon" c-variant="sidebar_item.icon_variant"
                                        c-href="sidebar_item.href" c-color="sidebar_link" c-text_attrs="icon_text_attrs">{{ sidebar_item.name }}</c-Icon>
                                </li>
                                <li c-for="child_item in sidebar_item.children or []" c-class="['ml-8 rounded-md', sidebar_link]">
                                    <c-Button variant="plain" c-href="child_item.href" c-attrs="child_btn_attrs">{{ child_item.name }}</c-Button>
                                </li>
                            </c-for>
                        </ul>
                        <li class="mt-auto">
                            <c-Icon name="user-group" variant="outline" c-href="faq_url" c-color="sidebar_link"
                                c-text_attrs="icon_text_attrs">FAQ</c-Icon>
                            <c-Icon name="megaphone" variant="outline" c-color="sidebar_link"
                                c-link_attrs="feedback_link_attrs" c-text_attrs="icon_text_attrs">Feedback</c-Icon>
                        </li>
                        <li c-if="is_staff">
                            <c-Icon name="document-arrow-down" variant="outline" c-color="sidebar_link"
                                c-text_attrs="icon_text_attrs">Download</c-Icon>
                        </li>
                    </li>
                </ul>
            </nav>
        </div>
    """


# ----- Base (document shell; <c-css>/<c-js> are feature C) -----


def static(path):
    return f"/static/{path}"


class Base(Component):
    citry = app
    name = "Base"

    js = """
        const app = { query: createQueryManager() };
        app.query.load();
        const createQueryManager = () => {
            const callbacks = {};
            const previousParamValues = {};
            const registerParam = (key, cb) => {
                callbacks[key] = callbacks[key] || [];
                callbacks[key].push(cb);
                return () => { callbacks[key] = (callbacks[key] || []).filter((c) => c !== cb); };
            };
            const setParams = (params) => {
                const url = new URL(location.href);
                Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
                history.pushState({}, "", url);
            };
            const load = () => {};
            return { registerParam, setParams, load };
        };
    """

    def template_data(self, kwargs, slots=None):
        return {
            "csrf_token": self.inject("render_context").render_context.csrf_token,
            "background": theme.background,
            "htmx_url": static("js/htmx.js"),
        }

    template = """
        <!DOCTYPE html>
        <html lang="en" class="h-full">
        <head>
            <meta charset="UTF-8">
            <meta http-equiv="X-UA-Compatible" content="IE=edge">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>DEMO</title>
            <c-css />
            <c-slot name="css" />
        </head>
        <body c-class="[background, 'h-full']">
            <c-slot name="content" />
            <script src="//unpkg.com/@alpinejs/anchor" defer></script>
            <script src="https://cdn.jsdelivr.net/npm/alpine-reactivity@0.1.10/dist/cdn.min.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/alpine-composition@0.1.27/dist/cdn.min.js"></script>
            <script src="//unpkg.com/alpinejs" defer></script>
            <script type="text/javascript" c-src="htmx_url"></script>
            <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
            <c-js />
            <c-slot name="js" />
            <script>
                (function () {
                    const token = '{{ csrf_token }}';
                    document.body.addEventListener('htmx:configRequest', (event) => {
                        event.detail.headers['X-CSRFToken'] = token;
                    });
                    document.addEventListener('alpine:init', () => {
                        Alpine.store('csrf', { token });
                    });
                })();
            </script>
        </body>
        </html>
    """


# ----- Layout -----


class LayoutData(NamedTuple):
    request: Any
    active_projects: list


class Layout(Component):
    citry = app
    name = "Layout"

    js = """
        document.addEventListener('alpine:init', () => {
            const computeSidebarState = (prevState) => {
                const width = (window.innerWidth > 0) ? window.innerWidth : screen.width;
                if (!prevState && width >= 1024) return true;
                if (prevState && width < 1024) return false;
                return prevState;
            };
            Alpine.data('layout', () => ({
                sidebarOpen: computeSidebarState(false),
                init() { this.onWindowResize(); },
                toggleSidebar() { this.sidebarOpen = !this.sidebarOpen; },
                onWindowResize() { this.sidebarOpen = computeSidebarState(this.sidebarOpen); },
            }));
        });
    """

    class Kwargs:
        data: Any
        attrs: dict | None = None

    def template_data(self, kwargs, slots=None):
        return {
            "request": kwargs.data.request,
            "active_projects": kwargs.data.active_projects,
            "attrs": kwargs.attrs,
            "navbar_attrs": {"@sidebar_toggle": "toggleSidebar"},
        }

    template = """
        <c-RenderContextProvider c-request="request">
            <c-Base>
                <c-fill name="js"><c-slot name="js" /></c-fill>
                <c-fill name="css"><c-slot name="css" /></c-fill>
                <c-fill name="content">
                    <div x-data="layout" @resize.window="onWindowResize" c-bind="attrs">
                        <div class="hidden" :class="{ 'fixed inset-y-0 z-40 flex w-72 flex-col': sidebarOpen, 'hidden': !sidebarOpen }">
                            <c-Sidebar c-active_projects="active_projects">
                                <c-fill name="content"><c-slot name="sidebar" /></c-fill>
                            </c-Sidebar>
                        </div>
                        <div :class="{ 'pl-72': sidebarOpen }" class="flex flex-col" style="height: 100vh;">
                            <c-Navbar c-attrs="navbar_attrs" />
                            <main class="flex-auto flex flex-col">
                                <c-slot name="header" />
                                <div class="px-4 pt-10 sm:px-6 lg:px-8 flex-auto flex flex-col">
                                    <c-slot name="content" />
                                </div>
                            </main>
                        </div>
                    </div>
                </c-fill>
            </c-Base>
        </c-RenderContextProvider>
    """


# ----- ProjectLayoutTabbed -----


def gen_tabs(project_id):
    return [
        TabStaticEntry(header="Tab 2", href=f"/projects/{project_id}/tab-2", content=None),
        TabStaticEntry(header="Tab 1", href=f"/projects/{project_id}/tab-1", content=None),
    ]


# The breadcrumb home icon never varies, so it is built once at import rather
# than on every layout render (a component instance is reusable; rendering it
# does not mutate it).
_HOME_ICON = Icon(name="home", variant="outline", size=20, stroke_width=2, color="text-gray-400 hover:text-gray-500")


class ProjectLayoutTabbed(Component):
    citry = app
    name = "ProjectLayoutTabbed"

    class Kwargs:
        data: Any
        breadcrumbs: list | None = None
        top_level_tab_index: int | None = None
        variant: Literal["thirds", "halves"] = "thirds"

    def template_data(self, kwargs, slots=None):
        data = kwargs.data
        project = data.project
        prefixed_breadcrumbs = [
            Breadcrumb(link="/projects", value=_HOME_ICON),
            Breadcrumb(value=project["name"], link=f"/projects/{project['id']}"),
            *(kwargs.breadcrumbs or []),
        ]
        is_thirds = kwargs.variant == "thirds"
        return {
            "layout_data": data,
            "breadcrumbs": prefixed_breadcrumbs,
            "bookmarks": data.bookmarks,
            "project_id": project["id"],
            "top_level_tabs": gen_tabs(project["id"]),
            "top_level_tab_index": kwargs.top_level_tab_index,
            "has_left_panel": bool(self.raw_slots.get("left_panel")),
            "left_panel_attrs": {"class": "w-1/3" if is_thirds else "w-1/2"},
            "right_panel_attrs": {"class": "w-2/3" if is_thirds else "w-1/2"},
            "tabs_attrs": {"class": "p-6 h-full"},
            "tabs_content_attrs": {"class": "flex flex-col"},
        }

    template = """
        <c-Layout c-data="layout_data">
            <c-fill name="js"><c-slot name="js" /></c-fill>
            <c-fill name="css"><c-slot name="css" /></c-fill>
            <c-fill name="header"><c-Breadcrumbs c-items="breadcrumbs" /></c-fill>
            <c-fill name="sidebar"><c-Bookmarks c-bookmarks="bookmarks" c-project_id="project_id" /></c-fill>
            <c-fill name="content">
                <c-slot name="header" />
                <c-TabsStatic c-if="top_level_tab_index is not None" c-tabs="top_level_tabs" c-index="top_level_tab_index" />
                <div class="flex flex-auto gap-6">
                    <div c-if="has_left_panel" c-bind="left_panel_attrs" c-class="'relative h-full pb-4'">
                        <div class="absolute w-full h-full"><c-slot name="left_panel" /></div>
                    </div>
                    <c-element c-is="has_left_panel and 'div' or 'template'" c-bind="has_left_panel and right_panel_attrs or {}"
                        c-class="has_left_panel and 'h-full' or ''">
                        <c-slot name="content">
                            <div class="h-full divide-y divide-gray-200 bg-white shadow overflow-y-hidden">
                                <c-Tabs name="proj-right" c-attrs="tabs_attrs" c-content_attrs="tabs_content_attrs">
                                    <c-slot name="tabs" />
                                </c-Tabs>
                            </div>
                        </c-slot>
                    </c-element>
                </div>
            </c-fill>
        </c-Layout>
    """


# ----- ProjectPage (root) -----


class ProjectPage(Component):
    citry = app
    name = "ProjectPage"

    class Kwargs:
        phases: list
        project_tags: list
        notes_1: list
        comments_by_notes_1: dict
        notes_2: list
        comments_by_notes_2: dict
        notes_3: list
        comments_by_notes_3: dict
        status_updates: list
        roles_with_users: list
        contacts: list
        outputs: list
        user_is_project_member: bool
        user_is_project_owner: bool
        phase_titles: dict
        layout_data: Any
        project: Any
        breadcrumbs: list | None = None

    def template_data(self, kwargs, slots=None):
        project = kwargs.project
        phases_by_type = {p["phase_template"]["type"]: p for p in kwargs.phases}
        rendered_phases = [
            ListItem(
                value=kwargs.phase_titles[pm.type],
                link=f"/projects/{project['id']}/phases/{phases_by_type[pm.type]['phase_template']['type']}",
            )
            for pm in PROJECT_PHASES_META.values()
        ]
        return {
            "layout_data": kwargs.layout_data,
            "project": project,
            "breadcrumbs": kwargs.breadcrumbs or [],
            "project_tags": kwargs.project_tags,
            "rendered_phases": rendered_phases,
            "contacts": kwargs.contacts,
            "notes_1": kwargs.notes_1,
            "comments_by_notes_1": kwargs.comments_by_notes_1,
            "notes_2": kwargs.notes_2,
            "comments_by_notes_2": kwargs.comments_by_notes_2,
            "notes_3": kwargs.notes_3,
            "comments_by_notes_3": kwargs.comments_by_notes_3,
            "status_updates": kwargs.status_updates,
            "roles_with_users": kwargs.roles_with_users,
            "outputs": kwargs.outputs,
            "user_is_project_member": kwargs.user_is_project_member,
            "user_is_project_owner": kwargs.user_is_project_owner,
            "phase_titles": kwargs.phase_titles,
            "phases_list_item_attrs": {"class": "py-5"},
        }

    template = """
        <c-ProjectLayoutTabbed c-data="layout_data" c-breadcrumbs="breadcrumbs" c-top_level_tab_index="1">
            <c-fill name="header">
                <div class="flex pb-6">
                    <div class="flex justify-between gap-x-12">
                        <div class="prose"><h3>{{ project['name'] }}</h3></div>
                        <div class="prose font-semibold text-gray-500 pt-1">{{ project['start_date'] }} - {{ project['end_date'] }}</div>
                    </div>
                </div>
            </c-fill>
            <c-fill name="left_panel">
                <c-List c-items="rendered_phases" c-item_attrs="phases_list_item_attrs" />
            </c-fill>
            <c-fill name="tabs">
                <c-TabItem header="Project Info">
                    <c-ProjectInfo c-project="project" c-project_tags="project_tags" c-roles_with_users="roles_with_users"
                        c-contacts="contacts" c-status_updates="status_updates" c-editable="user_is_project_owner" />
                </c-TabItem>
                <c-TabItem header="Notes 1">
                    <c-ProjectNotes c-project_id="project['id']" c-notes="notes_1" c-comments_by_notes="comments_by_notes_1" c-editable="user_is_project_member" />
                </c-TabItem>
                <c-TabItem header="Notes 2">
                    <c-ProjectNotes c-project_id="project['id']" c-notes="notes_2" c-comments_by_notes="comments_by_notes_2" c-editable="user_is_project_member" />
                </c-TabItem>
                <c-TabItem header="Notes 3">
                    <c-ProjectNotes c-project_id="project['id']" c-notes="notes_3" c-comments_by_notes="comments_by_notes_3" c-editable="user_is_project_member" />
                </c-TabItem>
                <c-TabItem header="Outputs">
                    <c-ProjectOutputsSummary c-project_id="project['id']" c-outputs="outputs" c-editable="user_is_project_member" c-phase_titles="phase_titles" />
                </c-TabItem>
            </c-fill>
        </c-ProjectLayoutTabbed>
    """


# ----------- TESTS START ------------ #
# The code above is also used when benchmarking.
# The section below is NOT included.

# The full page is non-deterministic (naturaltime is relative to now, the
# per-render `data-cid-*` markers are random), so this is a structural smoke
# test: it guards that the benchmarked logic still renders the whole page.


def test_render():
    data = gen_render_data()
    rendered = render(data)
    assert len(rendered) > 50_000  # the full project page, not a truncated render
    for anchor in ("<!DOCTYPE html>", "Project Name", "<body", "x-data"):
        assert anchor in rendered
