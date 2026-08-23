import unittest
from unittest.mock import patch

import httpx
from pydantic import BaseModel, ConfigDict, Field

from chat_backend import (
    ApprovedOperation,
    ChatProvider,
    ChatToolError,
    _provider_completion,
    build_tools_from_openapi,
    describe_provider_error,
    execute_approved_operation,
    run_groq_tool_chat,
    run_provider_tool_chat,
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

    @patch("chat_backend.httpx.post")
    def test_local_completion_disables_hidden_reasoning(self, post):
        post.return_value.raise_for_status.return_value = None
        post.return_value.json.return_value = {
            "choices": [{"message": {"content": "ready"}}]
        }

        result = _provider_completion(
            provider=ChatProvider(
                name="local",
                api_key="ollama",
                base_url="http://127.0.0.1:11434/v1",
                model="qwen3:8b",
            ),
            messages=[{"role": "user", "content": "status"}],
            tools=[],
        )

        self.assertEqual(result["content"], "ready")
        request_body = post.call_args.kwargs["json"]
        self.assertEqual(request_body["reasoning_effort"], "none")
        self.assertEqual(request_body["max_tokens"], 1200)

    @patch("chat_backend._provider_completion")
    def test_tool_call_is_executed_then_returned_to_model(self, completion):
        responses = iter(
            [
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
        )
        prompts = []

        def complete(**kwargs):
            prompts.append(kwargs["messages"][0]["content"])
            return next(responses)

        completion.side_effect = complete

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

        routing_prompt = prompts[0]
        self.assertIn("status must be exactly one of", routing_prompt)
        self.assertIn("completed or finished", routing_prompt)
        self.assertNotIn("62 to 66", prompts[1])
        self.assertIn("actual returned scores", prompts[1])

    @patch("chat_backend._provider_completion")
    def test_invalid_tool_call_cannot_become_a_factual_answer(self, completion):
        completion.return_value = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "list_example",
                        "arguments": '{"limit": 50}',
                    },
                }
            ],
        }

        with self.assertRaisesRegex(
            ChatToolError,
            "after repair",
        ):
            run_provider_tool_chat(
                provider=ChatProvider(
                    name="local",
                    api_key="ollama",
                    base_url="http://127.0.0.1:11434/v1",
                    model="qwen3:8b",
                ),
                message="How many examples?",
                focus_topic=None,
                history=[],
                tools=build_tools_from_openapi(self.openapi, self.operations),
                approved_operations=self.operations,
                db=object(),
            )

        self.assertEqual(self.executed, [])
        self.assertEqual(completion.call_count, 2)

    @patch("chat_backend._provider_completion")
    def test_invalid_local_tool_call_is_repaired_once(self, completion):
        completion.side_effect = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "list_example",
                            "arguments": '{"limit": 50}',
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_fixed",
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

        result = run_provider_tool_chat(
            provider=ChatProvider(
                name="local",
                api_key="ollama",
                base_url="http://127.0.0.1:11434/v1",
                model="qwen3:8b",
            ),
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
        self.assertEqual(completion.call_count, 3)
        repair_messages = completion.call_args_list[1].kwargs["messages"]
        self.assertTrue(
            any(
                "Retry exactly one" in (item.get("content") or "")
                for item in repair_messages
            )
        )

    @patch("chat_backend._provider_completion")
    def test_server_can_force_operation_and_arguments(self, completion):
        completion.return_value = {
            "role": "assistant",
            "content": "There are two examples.",
        }

        result = run_provider_tool_chat(
            provider=ChatProvider(
                name="test",
                api_key="test-key",
                base_url="https://example.invalid/v1",
                model="test-model",
            ),
            message="Show last week",
            focus_topic=None,
            history=[],
            tools=build_tools_from_openapi(self.openapi, self.operations),
            approved_operations=self.operations,
            db=object(),
            forced_operation="list_example",
            forced_arguments={"limit": 2},
        )

        self.assertEqual(result.operations, ["list_example"])
        self.assertEqual(self.executed, [2])
        self.assertEqual(completion.call_count, 1)

    @patch("chat_backend._provider_completion")
    def test_visualization_prompt_cannot_invent_missing_scope(self, completion):
        prompts = []

        def complete(**kwargs):
            prompts.append(kwargs["messages"][0]["content"])
            return {
                "role": "assistant",
                "content": "The chart compares two categories. One is higher.",
            }

        completion.side_effect = complete

        run_provider_tool_chat(
            provider=ChatProvider(
                name="local",
                api_key="ollama",
                base_url="http://127.0.0.1:11434/v1",
                model="qwen3:8b",
            ),
            message="Compare categories",
            focus_topic=None,
            history=[],
            tools=build_tools_from_openapi(self.openapi, self.operations),
            approved_operations=self.operations,
            db=object(),
            request_intent="visualization",
            request_context=(
                "There is no date window and no overall attempt total; do not "
                "mention either."
            ),
            forced_operation="list_example",
            forced_arguments={"limit": 2},
        )

        self.assertEqual(completion.call_count, 1)
        self.assertIn("never invent or estimate either", prompts[0])
        self.assertIn("Do not claim causation", prompts[0])
        self.assertNotIn("first state the inclusive date window", prompts[0])


if __name__ == "__main__":
    unittest.main()
