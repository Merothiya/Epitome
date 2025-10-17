import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
from mytools import GithubAPI, RiskAnalyzer, MongoDBService
import re # For parsing tool calls

load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Initialize tools
risk_analyzer = RiskAnalyzer()
mongo_service = MongoDBService()

# Impact Analyzer Agent prompt template (adapted to guide LLM for tool use)
IMPACT_ANALYZER_PROMPT_TEMPLATE = """You are the Impact Analyzer Agent (A6). Your task is to analyze commit diffs and predict feature stability, providing a risk score.
You have access to the following tools:
{tool_descriptions}

Here are the details of the Pull Request you need to analyze:
{pr_details}

Here is the current repository vector memory (placeholder for now, will be used in later phases):
{repo_vector_memory}

Follow these steps:
1. Get the commit diff for the Pull Request using `GitHub_GetPRDiff`.
2. Use `RiskAnalyzer_AnalyzeDiff` to calculate the `estimated_risk_score` based on the commit diff and `repo_vector_memory`.
3. Log the risk analysis results to MongoDB using `MongoDB_InsertLog` with collection 'impact_analysis_cycles'. The log entry should include:
    - `pr_number`
    - `files_changed` (list of files from diff, can be inferred or extracted)
    - `tests_affected` (placeholder for now)
    - `historical_failure_rate` (placeholder for now)
    - `estimated_risk_score` (from RiskAnalyzer_AnalyzeDiff)

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
  "files_changed": [],
  "tests_affected": "...",
  "historical_failure_rate": "...",
  "estimated_risk_score": "..."
}}
</final_answer>

Begin!
"""

class ImpactAnalyzerAgent:
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
            "RiskAnalyzer_AnalyzeDiff": {
                "func": risk_analyzer.analyze_diff,
                "description": "Analyzes a commit diff and provides a risk score. Input: commit_diff (str), repo_vector_memory (dict, placeholder for now)."
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

    def run_analysis(self, pr_number, pr_details, repo_vector_memory={}):
        if isinstance(pr_details, dict):
            pr_details_str = json.dumps(pr_details, indent=2)
        else:
            pr_details_str = str(pr_details)

        repo_vector_memory_str = json.dumps(repo_vector_memory, indent=2)

        tool_descriptions = self._format_tool_descriptions()

        current_prompt = IMPACT_ANALYZER_PROMPT_TEMPLATE.format(
            tool_descriptions=tool_descriptions,
            pr_details=pr_details_str,
            repo_vector_memory=repo_vector_memory_str
        )

        max_iterations = 10 # Prevent infinite loops

        for i in range(max_iterations):
            print(f"--- Impact Analyzer Agent Iteration {i+1} ---")
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
            "message": "Impact Analyzer Agent reached max iterations without providing a final answer.",
            "raw_response": response_text
        }

if __name__ == "__main__":
    # Example usage
    # impact_analyzer = ImpactAnalyzerAgent(repo_name="test-autonomous-devops")
    # pr_details = {
    #     "id": 1,
    #     "title": "feat: added dark mode toggle",
    #     "author": "builder-agent",
    #     "url": "https://github.com/your_user/test-autonomous-devops/pull/1"
    # }
    # impact_analyzer.run_analysis(pr_number=1, pr_details=pr_details)
    pass
