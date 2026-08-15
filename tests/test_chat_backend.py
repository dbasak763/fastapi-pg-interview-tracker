import unittest
from unittest.mock import patch

from pydantic import BaseModel, ConfigDict, Field

from chat_backend import (
    ApprovedOperation,
    ChatToolError,
    build_tools_from_openapi,
    execute_approved_operation,
    run_groq_tool_chat,
)


class ExampleArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=5, ge=1, le=10)


class ChatBackendTests(unittest.TestCase):
    def setUp(self):
        self.executed = []

        def executor(arguments, db):
            self.executed.append(arguments.limit)
            return {"items": [1, 2], "limit": arguments.limit}

        self.operations = {
            "list_example": ApprovedOperation(
                arguments_model=ExampleArguments,
                executor=executor,
            )
        }
        self.openapi = {
            "paths": {
                "/read": {
                    "get": {
                        "operationId": "list_example",
                        "summary": "Read examples",
                        "parameters": [
                            {
                                "name": "limit",
                                "in": "query",
                                "required": False,
                                "schema": {
                                    "type": "integer",
                                    "default": 5,
                                    "minimum": 1,
                                },
                            }
                        ],
                    },
                    "post": {
                        "operationId": "create_example",
                        "summary": "Create an example",
                    },
                }
            }
        }

    def test_swagger_builder_includes_only_allowlisted_get_operations(self):
        tools = build_tools_from_openapi(self.openapi, self.operations)

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["function"]["name"], "list_example")
        self.assertNotIn("create_example", str(tools))

    def test_approved_operation_validates_arguments_before_execution(self):
        result = execute_approved_operation(
            "list_example",
            '{"limit": 3}',
            self.operations,
            db=object(),
        )

        self.assertEqual(result["limit"], 3)
        self.assertEqual(self.executed, [3])

    def test_unapproved_operation_is_rejected(self):
        with self.assertRaises(ChatToolError):
            execute_approved_operation(
                "delete_everything",
                "{}",
                self.operations,
                db=object(),
            )

        self.assertEqual(self.executed, [])

    def test_invalid_arguments_are_rejected(self):
        with self.assertRaises(ChatToolError):
            execute_approved_operation(
                "list_example",
                '{"limit": 50, "sql": "DROP TABLE examples"}',
                self.operations,
                db=object(),
            )

        self.assertEqual(self.executed, [])

    @patch("chat_backend._provider_completion")
    def test_tool_call_is_executed_then_returned_to_model(self, completion):
        completion.side_effect = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "list_example",
                            "arguments": '{"limit": 2}',
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "There are two examples.",
            },
        ]

        result = run_groq_tool_chat(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="test-model",
            message="How many examples?",
            focus_topic=None,
            history=[],
            tools=build_tools_from_openapi(self.openapi, self.operations),
            approved_operations=self.operations,
            db=object(),
        )

        self.assertEqual(result.reply, "There are two examples.")
        self.assertEqual(result.operations, ["list_example"])
        self.assertEqual(self.executed, [2])
        self.assertEqual(completion.call_count, 2)


if __name__ == "__main__":
    unittest.main()
