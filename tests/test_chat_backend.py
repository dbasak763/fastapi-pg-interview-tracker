import unittest
from unittest.mock import patch

import httpx
from pydantic import BaseModel, ConfigDict, Field

from chat_backend import (
    ApprovedOperation,
    ChatToolError,
    build_tools_from_openapi,
    describe_provider_error,
    execute_approved_operation,
    run_groq_tool_chat,
    select_request_tools,
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

    def test_focused_question_only_exposes_topic_progression(self):
        tools = [
            {"type": "function", "function": {"name": "score_timeline"}},
            {
                "type": "function",
                "function": {"name": "topic_score_progression"},
            },
        ]

        selected = select_request_tools(
            tools,
            message="What is my latest score?",
            focus_topic="System Design",
        )

        self.assertEqual(
            [tool["function"]["name"] for tool in selected],
            ["topic_score_progression"],
        )

    def test_overall_question_keeps_cross_topic_tools(self):
        tools = [
            {"type": "function", "function": {"name": "score_timeline"}},
            {
                "type": "function",
                "function": {"name": "topic_score_progression"},
            },
        ]

        selected = select_request_tools(
            tools,
            message="Review every attempt",
            focus_topic="System Design",
        )

        self.assertEqual(selected, tools)

    def test_provider_error_description_includes_safe_groq_fields(self):
        request = httpx.Request("POST", "https://api.example.invalid/chat")
        response = httpx.Response(
            413,
            request=request,
            json={
                "error": {
                    "type": "tokens",
                    "code": "rate_limit_exceeded",
                    "message": "Internal account details should not be logged",
                }
            },
        )
        error = httpx.HTTPStatusError(
            "request failed",
            request=request,
            response=response,
        )

        description = describe_provider_error(error)

        self.assertEqual(
            description,
            "HTTPStatusError status=413 type=tokens code=rate_limit_exceeded",
        )
        self.assertNotIn("account details", description)

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
