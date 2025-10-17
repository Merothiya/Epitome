import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
from mytools import GithubAPI, MongoDBService
import re # For parsing tool calls

load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Initialize tools
mongo_service = MongoDBService()

# Reviewer Agent prompt template (adapted to guide LLM for tool use)
REVIEWER_PROMPT_TEMPLATE = """You are the Reviewer Agent (A2). Your task is to review Pull Requests for code quality, style, complexity, and logical correctness.
You have access to the following tools:
{tool_descriptions}

Here are the details of the Pull Request you need to review:
{pr_details}

Here is the commit diff for the Pull Request:
{commit_diff}

Follow these steps:
1. Analyze the `commit_diff` for code quality, style (using flake8 principles), complexity (using radon principles), and logical correctness.
2. Identify any potential bugs, areas for improvement, or suggestions.
3. Generate structured review comments.
4. Log your review findings to MongoDB using `MongoDB_InsertLog` with collection 'review_cycles'. The log entry should include:
    - `pr_number`
    - `review_summary` (overall assessment)
    - `suggestions` (list of suggested changes/comments)
    - `code_quality_score` (e.g., 1-10)
    - `complexity_score` (e.g., 1-10)
    - `test_logic_validation` (assessment of test logic)

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
  "pr_number": "...",
  "review_summary": "...",
  "suggestions": [],
  "code_quality_score": "...",
  "complexity_score": "...",
  "test_logic_validation": "..."
}}
</final_answer>

Begin!
"""

class ReviewerAgent:
    def __init__(self, github_api, model_name="gemini-2.5-flash", temperature=0.7):
        self.github_api = github_api
        self.llm = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"temperature": temperature}
        )
        self.tools = {
            "GitHub_GetPRDiff": {
                "func": self.github_api.get_pr_diff,
                "description": "Retrieves the diff of a Pull Request. Input: pr_number (int)."
            },
            "GitHub_CreateCommit": { # Re-using for adding review comments if needed
                "func": self.github_api.commit_file,
                "description": "Commits changes to a file in the GitHub repository. Input: file_path, content, message, branch (optional, defaults to 'main')."
            },
            "MongoDB_InsertLog": {
                "func": mongo_service.insert_log,
                "description": "Inserts a log entry into a MongoDB collection. Input: collection_name, log_entry (dict)."
            }
        }

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

    def run_review(self, pr_number, pr_details):
        commit_diff = self.github_api.get_pr_diff(pr_number)
        
        if isinstance(pr_details, dict):
            pr_details_str = json.dumps(pr_details, indent=2)
        else:
            pr_details_str = str(pr_details)

        tool_descriptions = self._format_tool_descriptions()

        current_prompt = REVIEWER_PROMPT_TEMPLATE.format(
            tool_descriptions=tool_descriptions,
            pr_details=pr_details_str,
            commit_diff=commit_diff
        )

        max_iterations = 10 # Prevent infinite loops

        for i in range(max_iterations):
            print(f"--- Reviewer Agent Iteration {i+1} ---")
            print(f"Sending prompt to LLM:\n{current_prompt[-500:]}...")

            response = self.llm.generate_content(current_prompt)
            response_text = response.text
            print(f"LLM Response:\n{response_text}")

            final_answer = self._parse_final_answer(response_text)
            if final_answer:
                print("Final answer received.")
                return final_answer

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
            "message": "Reviewer Agent reached max iterations without providing a final answer.",
            "raw_response": response_text
        }

if __name__ == "__main__":
    # Example usage (replace with your actual repo name and PR number)
    # reviewer = ReviewerAgent(repo_name="test-autonomous-devops")
    # pr_details = {
    #     "id": 1,
    #     "title": "feat: added dark mode toggle",
    #     "author": "builder-agent",
    #     "url": "https://github.com/your_user/test-autonomous-devops/pull/1"
    # }
    # reviewer.run_review(pr_number=1, pr_details=pr_details)
    pass
