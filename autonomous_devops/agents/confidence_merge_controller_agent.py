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

# Confidence & Merge Controller Agent prompt template (adapted to guide LLM for tool use)
MERGE_CONTROLLER_PROMPT_TEMPLATE = """You are the Confidence & Merge Controller Agent (A5). Your task is to collect results from other agents, calculate a confidence level, and decide whether to automatically merge a Pull Request.
You have access to the following tools:
{tool_descriptions}

Here are the collected results:
- Test Results (from Builder A1): {test_results}
- Review Feedback (from Reviewer A2): {review_feedback}
- QA Report (from QA Agent A4): {qa_report}
- Risk Score (from Impact Analyzer A6): {risk_score}

Here are the details of the Pull Request:
{pr_details}

Follow these steps:
1. Parse the `test_results`, `review_feedback`, `qa_report`, and `risk_score`.
2. Calculate the confidence level using the formula:
   `confidence = (tests_pass * 0.4) + (review_score * 0.3) + (qa_pass * 0.2) - ((risk_score / 10) * 0.3)`
   - `tests_pass`: 1 if tests passed, 0 otherwise.
   - `review_score`: Assume 1 for approved, 0 for not approved (can be refined later).
   - `qa_pass`: 1 if no UI bugs detected, 0 otherwise.
   - `risk_score`: The estimated risk score from A6 (0-10).
3. If `confidence > 0.85`, then merge the PR automatically using `GitHub_MergePR`.
4. Log the merge decision (or rejection) and the calculated confidence to MongoDB using `MongoDB_InsertLog` with collection 'merge_cycles'. The log entry should include:
    - `pr_number`
    - `confidence_score`
    - `merge_decision` (merged/rejected)
    - `reason` (e.g., "Confidence above threshold", "Low confidence")
    - `explainable_merge_log` (human-readable summary)

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
  "confidence_score": "...",
  "merge_decision": "merged" | "rejected",
  "reason": "...",
  "explainable_merge_log": "..."
}}
</final_answer>

Begin!
"""

class ConfidenceMergeControllerAgent:
    def __init__(self, github_api, model_name="gemini-2.5-flash", temperature=0.7):
        self.github_api = github_api
        self.llm = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"temperature": temperature}
        )
        self.tools = {
            "GitHub_CreateCommit": { # Can be used for adding merge commit if needed
                "func": self.github_api.commit_file,
                "description": "Commits changes to a file in the GitHub repository. Input: file_path, content, message, branch (optional, defaults to 'main')."
            },
            "MongoDB_InsertLog": {
                "func": mongo_service.insert_log,
                "description": "Inserts a log entry into a MongoDB collection. Input: collection_name, log_entry (dict)."
            },
            "GitHub_MergePR": { # Placeholder for actual merge functionality
                "func": self.github_api.merge_pr,
                "description": "Merges a Pull Request. Input: pr_number (int), commit_title (str)."
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

    def run_merge_decision(self, test_results, review_feedback, qa_report, risk_score, pr_details):
        test_results_str = json.dumps(test_results, indent=2) if isinstance(test_results, dict) else str(test_results)
        review_feedback_str = json.dumps(review_feedback, indent=2) if isinstance(review_feedback, dict) else str(review_feedback)
        qa_report_str = json.dumps(qa_report, indent=2) if isinstance(qa_report, dict) else str(qa_report)
        pr_details_str = json.dumps(pr_details, indent=2) if isinstance(pr_details, dict) else str(pr_details)

        tool_descriptions = self._format_tool_descriptions()

        current_prompt = MERGE_CONTROLLER_PROMPT_TEMPLATE.format(
            tool_descriptions=tool_descriptions,
            test_results=test_results_str,
            review_feedback=review_feedback_str,
            qa_report=qa_report_str,
            risk_score=risk_score,
            pr_details=pr_details_str
        )

        max_iterations = 10 # Prevent infinite loops

        for i in range(max_iterations):
            print(f"--- Confidence & Merge Controller Agent Iteration {i+1} ---")
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
            "message": "Confidence & Merge Controller Agent reached max iterations without providing a final answer.",
            "raw_response": response_text
        }

if __name__ == "__main__":
    # Example usage
    # merge_controller = ConfidenceMergeControllerAgent(repo_name="test-autonomous-devops")
    # test_res = {"success": True, "output": "tests passed"}
    # review_fb = {"review_summary": "Approved", "code_quality_score": 8}
    # qa_rep = {"ui_bugs_detected": False, "qa_summary": "No major issues"}
    # risk_sc = {"estimated_risk_score": 2.5}
    # pr_det = {"id": 1, "title": "feat: dark mode"}
    # merge_controller.run_merge_decision(test_res, review_fb, qa_rep, risk_sc, pr_det)
    pass
