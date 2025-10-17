import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
from mytools import SeleniumTester, CIManager, MongoDBService
import re # For parsing tool calls

load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Initialize tools
selenium_tester = SeleniumTester()
ci_manager = CIManager()
mongo_service = MongoDBService()

# Define the QA Agent's tools
QA_TOOLS = {
    "CIManager_DeployToVercel": {
        "func": ci_manager.deploy_to_vercel,
        "description": "Deploys the project to Vercel. Input: project_path."
    },
    "CIManager_DeployToDocker": {
        "func": ci_manager.deploy_to_docker,
        "description": "Deploys the project using Docker. Input: project_path."
    },
    "Selenium_DeployAndTestUI": {
        "func": selenium_tester.deploy_and_test_ui,
        "description": "Deploys a preview and runs UI interaction tests using Selenium. Input: deploy_url (str), actions (list of dicts, e.g., [{'type': 'click', 'selector': '#button_id'}])."
    },
    "MongoDB_InsertLog": {
        "func": mongo_service.insert_log,
        "description": "Inserts a log entry into a MongoDB collection. Input: collection_name, log_entry (dict)."
    }
}

# QA Agent prompt template (adapted to guide LLM for tool use)
QA_PROMPT_TEMPLATE = """You are the QA Agent (A4). Your task is to perform exploratory testing on temporary deployments.
You have access to the following tools:
{tool_descriptions}

Here is the feature ticket that was implemented:
{feature_ticket}

The deployment method specified is: {deploy_method}
The project path is: {project_path}

Follow these steps:
1. Deploy the project using the specified `deploy_method` (either `CIManager_DeployToVercel` or `CIManager_DeployToDocker`).
2. Once deployed, use `Selenium_DeployAndTestUI` to interact with the UI.
3. Based on the `feature_ticket` description, devise a series of UI interaction `actions` (clicks, types, etc.) to test the new feature.
4. Capture screenshots and browser logs during testing.
5. Log the QA report to MongoDB using `MongoDB_InsertLog` with collection 'qa_cycles'. The log entry should include:
    - `feature_ticket_id`
    - `deploy_url`
    - `test_actions` (list of actions performed)
    - `screenshots` (list of paths to screenshots)
    - `browser_logs`
    - `ui_bugs_detected` (boolean)
    - `qa_summary` (overall assessment)

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
  "feature_ticket_id": "...",
  "deploy_url": "...",
  "test_actions": [],
  "screenshots": [],
  "browser_logs": "...",
  "ui_bugs_detected": true | false,
  "qa_summary": "..."
}}
</final_answer>

Begin!
"""

class QAAgent:
    def __init__(self, model_name="gemini-2.5-flash", temperature=0.7):
        self.llm = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"temperature": temperature}
        )
        self.tools = QA_TOOLS

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

    def run_qa(self, feature_ticket, deploy_method="vercel", project_path="."):
        if isinstance(feature_ticket, dict):
            feature_ticket_str = json.dumps(feature_ticket, indent=2)
        else:
            feature_ticket_str = str(feature_ticket)

        tool_descriptions = self._format_tool_descriptions()

        current_prompt = QA_PROMPT_TEMPLATE.format(
            tool_descriptions=tool_descriptions,
            feature_ticket=feature_ticket_str,
            deploy_method=deploy_method,
            project_path=project_path
        )

        max_iterations = 10 # Prevent infinite loops

        for i in range(max_iterations):
            print(f"--- QA Agent Iteration {i+1} ---")
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
            "message": "QA Agent reached max iterations without providing a final answer.",
            "raw_response": response_text
        }

if __name__ == "__main__":
    # Example usage
    # qa_agent = QAAgent()
    # feature = {
    #     "id": "F102",
    #     "title": "Add dark mode toggle",
    #     "description": "Implement a dark mode toggle in navbar with local storage persistence.",
    #     "priority": "high"
    # }
    # qa_agent.run_qa(feature_ticket=feature, deploy_method="vercel", project_path="../test_frontend_app")
    pass
