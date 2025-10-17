import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
from google.api_core import exceptions
from mytools import GithubAPI, SeleniumTester, MongoDBService # Keep these for tool definitions
import re # For parsing tool calls
import time # For sleep in retry
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type # For retry mechanism

load_dotenv()


# Configure Gemini API
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Initialize tools
selenium_tester = SeleniumTester()
mongo_service = MongoDBService()

# Builder Agent prompt template (adapted to guide LLM for tool use)
BUILDER_PROMPT_TEMPLATE = """You are the Builder Agent (A1). Your task is to implement new features and write corresponding Selenium tests.
You have access to the following tools:
{tool_descriptions}

Here is the feature ticket you need to implement:
{feature_ticket}

Here is the current repository context (important files and their content):
{repo_context}

Follow these steps:
1. Analyze the feature ticket and the repository context to understand the task.
2. Determine which files need to be modified or created to implement the feature.
3. Generate the code for the feature implementation.
4. Generate a Selenium test file (e.g., `tests/test_feature.py`) to verify the feature.
5. **IMPORTANT**: You MUST use `LocalFile_Write` to write the feature code and the test code to the local repository at `{local_repo_path}`. DO NOT use any GitHub-related tools for file creation or modification.
6. Use `Selenium_RunTests` to run the newly created tests.
7. If tests pass, provide a final answer indicating success and that local changes are ready for Git workflow.
8. If tests fail, attempt to self-debug the code and tests up to 2 iterations. After 2 failed attempts, provide a final answer indicating failure.

You must respond in a specific format.
To use a tool, respond with:
<tool_code>
{{
  "tool_name": "ToolName",
  "parameters": {{
    "param1": "value1",
    "param2": "value2"
  }}
}}
</tool_code>

To provide your final answer, respond with a JSON object:
<final_answer>
{{
  "status": "success" | "failure",
  "message": "...",
  "local_changes_made": true | false
}}
</final_answer>

Begin!
"""

class BuilderAgent:
    def __init__(self, github_api, local_repo_path, model_name="gemini-2.5-flash", temperature=0.7):
        self.github_api = github_api
        self.local_repo_path = local_repo_path
        self.llm = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"temperature": temperature}
        )
        self.tools = {
            "GitHub_GetRepoContent": {
                "func": self.github_api.get_repo_content,
                "description": "Reads content from the GitHub repository. Input: path (optional, defaults to root)."
            },
            "LocalFile_Write": {
                "func": self._local_file_write,
                "description": "Writes content to a local file within the repository. Input: file_path (relative to local_repo_path), content."
            },
            "Selenium_RunTests": {
                "func": selenium_tester.run_tests,
                "description": "Runs pytest Selenium tests locally. Input: test_file_path."
            },
            "MongoDB_InsertLog": {
                "func": mongo_service.insert_log,
                "description": "Inserts a log entry into a MongoDB collection. Input: collection_name, log_entry (dict)."
            }
        }

    def _local_file_write(self, file_path, content):
        """
        Writes content to a file within the local repository path.
        Automatically creates directories if they don't exist.
        """
        full_path = os.path.join(self.local_repo_path, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w') as f:
            f.write(content)
        return f"Successfully wrote to {full_path}"

    def _format_tool_descriptions(self):
        descriptions = []
        for name, tool_info in self.tools.items():
            descriptions.append(f"- {name}: {tool_info['description']}")
        return "\n".join(descriptions)

    def _parse_tool_code(self, text):
        match = re.search(r'<tool_code>(.*?)</tool_code>', text, re.DOTALL)
        if match:
            try:
                tool_call = json.loads(match.group(1).strip())
                return tool_call.get("tool_name"), tool_call.get("parameters", {})
            except json.JSONDecodeError:
                return None, None
        return None, None

    def _parse_final_answer(self, text):
        match = re.search(r'<final_answer>(.*?)</final_answer>', text, re.DOTALL)
        if match:
            try:
                final_answer = json.loads(match.group(1).strip())
                return final_answer
            except json.JSONDecodeError:
                return None
        return None

    def run(self, feature_ticket):
        repo_context = self.github_api.get_repo_content()

        if isinstance(feature_ticket, dict):
            feature_ticket_str = json.dumps(feature_ticket, indent=2)
        else:
            feature_ticket_str = str(feature_ticket)

        tool_descriptions = self._format_tool_descriptions()
        
        # Determine the feature branch name (still useful for context, even if not creating it here)
        feature_branch_name = f"feature/{feature_ticket['feature_id']}-{feature_ticket['title'].replace(' ', '-').lower()}"
        feature_branch_name = re.sub(r'[^a-zA-Z0-9\-_]', '-', feature_branch_name)
        feature_branch_name = feature_branch_name[:100]

        current_prompt = BUILDER_PROMPT_TEMPLATE.format(
            tool_descriptions=tool_descriptions,
            feature_ticket=feature_ticket_str,
            repo_context=repo_context,
            local_repo_path=self.local_repo_path # Pass local repo path to prompt
        )

        chat_history = []
        max_iterations = 10

        for i in range(max_iterations):
            print(f"--- Builder Agent Iteration {i+1} ---")
            print(f"Sending prompt to LLM:\n{current_prompt[-500:]}...")

            @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3),
                   retry=retry_if_exception_type(exceptions.ResourceExhausted))
            def _generate_content_with_retry(prompt_text):
                return self.llm.generate_content(prompt_text)

            try:
                response = _generate_content_with_retry(current_prompt)
            except exceptions.ResourceExhausted as e:
                print(f"Quota exceeded after retries: {e}")
                return {
                    "status": "failure",
                    "message": f"Builder Agent failed due to Gemini API quota exhaustion: {e}",
                    "local_changes_made": False
                }
            except Exception as e:
                print(f"An unexpected error occurred during content generation: {e}")
                return {
                    "status": "failure",
                    "message": f"Builder Agent failed due to an unexpected error: {e}",
                    "local_changes_made": False
                }

            response_text = ""
            if response.parts:
                response_text = response.text
            else:
                print("LLM Response had no text parts. Finish reason:", response.candidates[0].finish_reason)
            print(f"LLM Response:\n{response_text}")

            final_answer_data = self._parse_final_answer(response_text)
            if final_answer_data:
                print("Final answer received.")
                # The Builder Agent no longer handles PR creation, so it should not return PR details.
                # Ensure only relevant fields are returned.
                if "pr_url" in final_answer_data:
                    del final_answer_data["pr_url"]
                if "pr_number" in final_answer_data:
                    del final_answer_data["pr_number"]
                return final_answer_data

            tool_name, tool_params = self._parse_tool_code(response_text)
            if tool_name and tool_name in self.tools:
                print(f"Tool call identified: {tool_name} with params {tool_params}")
                tool_func = self.tools[tool_name]["func"]
                
                try:
                    tool_output = tool_func(**tool_params)
                    print(f"Tool output: {tool_output}")
                    current_prompt += f"\n\nTool Output for {tool_name}:\n{tool_output}\n\n"
                except Exception as e:
                    print(f"Error executing tool {tool_name}: {e}")
                    current_prompt += f"\n\nTool Error for {tool_name}: {e}\n\n"
            else:
                print("No valid tool call or final answer found. Appending LLM response to prompt.")
                current_prompt += f"\n\nLLM Thought/Response:\n{response_text}\n\n"

        return {
            "status": "failure",
            "message": "Builder Agent reached max iterations without providing a final answer.",
            "local_changes_made": False
        }

if __name__ == "__main__":
    github_api = GithubAPI("Merothiya/Snakes-Ladders-and-Faith")
    # For testing, create a dummy local repo path
    test_local_repo_path = os.path.join(os.getcwd(), "test_repo_for_builder")
    os.makedirs(test_local_repo_path, exist_ok=True)

    builder = BuilderAgent(github_api, test_local_repo_path)

    feature = {
        "feature_id": "F101",
        "title": "Implement Light/Dark Mode Toggle with Preference Saving",
        "description": "As a user, I want to toggle between light and dark mode and persist my choice.",
        "priority": "high",
        "acceptance_criteria": [
            "Toggle visible in navbar",
            "Mode persisted in local storage"
        ]
    }

    result = builder.run(feature)
    print(json.dumps(result, indent=2))
