import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
import re
import time # For sleep in retry
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type # For retry mechanism
from google.api_core import exceptions # Import exceptions

load_dotenv()

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

PRODUCT_MANAGER_PROMPT_TEMPLATE = """You are the Product Manager Agent. Your task is to take raw user comments or feature requests and convert them into a structured JSON format suitable for development agents.

The JSON output should include the following fields:
- "feature_id": A unique identifier for the feature (e.g., "F101", "F102"). If not explicitly provided, generate one.
- "title": A concise title for the feature.
- "description": A detailed description of the feature, explaining its purpose and functionality.
- "priority": The priority of the feature (e.g., "high", "medium", "low"). Default to "medium" if not specified.
- "acceptance_criteria": A list of clear, testable criteria that define when the feature is considered complete.

Here is the user comment/feature request:
{user_comment}

Your output MUST be a JSON object, enclosed in <json_output> and </json_output> tags. Do NOT include any other text or explanation outside these tags.

Example JSON structure:
<json_output>
{{
  "feature_id": "F103",
  "title": "Implement User Profile Page",
  "description": "Develop a dedicated user profile page where users can view and edit their personal information, including name, email, and profile picture. The page should also display a list of their recent activities.",
  "priority": "high",
  "acceptance_criteria": [
    "User can navigate to their profile page.",
    "Profile page displays user's name, email, and profile picture.",
    "User can update their name and email.",
    "Profile picture can be uploaded and changed.",
    "Recent activities are listed on the profile page."
  ]
}}
</json_output>

Begin!
"""

class ProductManagerAgent:
    def __init__(self, model_name="gemini-2.5-flash", temperature=0.3): # Changed model to flash
        self.llm = genai.GenerativeModel(
            model_name=model_name,
            generation_config={"temperature": temperature}
        )

    def process_comment(self, user_comment):
        prompt = PRODUCT_MANAGER_PROMPT_TEMPLATE.format(user_comment=user_comment)
        
        max_iterations = 3
        for i in range(max_iterations):
            print(f"--- Product Manager Agent Iteration {i+1} ---")
            print(f"Sending prompt to LLM:\n{prompt[-500:]}...")

            @retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(3),
                   retry=retry_if_exception_type(exceptions.ResourceExhausted)) # Corrected exception reference
            def _generate_content_with_retry(prompt_text):
                return self.llm.generate_content(prompt_text)

            try:
                response = _generate_content_with_retry(prompt)
            except google.api_core.exceptions.ResourceExhausted as e:
                print(f"Quota exceeded after retries: {e}")
                return {
                    "status": "failure",
                    "message": f"Product Manager Agent failed due to Gemini API quota exhaustion: {e}",
                    "raw_response": ""
                }
            except Exception as e:
                print(f"An unexpected error occurred during content generation: {e}")
                return {
                    "status": "failure",
                    "message": f"Product Manager Agent failed due to an unexpected error: {e}",
                    "raw_response": ""
                }

            response_text = ""
            if response.parts:
                response_text = response.text
            else:
                print("LLM Response had no text parts. Finish reason:", response.candidates[0].finish_reason)
                prompt += "\n\nError: LLM did not return any text. Please provide a valid JSON output."
                continue

            print(f"LLM Raw Response:\n{response_text}")

            # Extract JSON from between <json_output> tags
            match = re.search(r'<json_output>(.*?)</json_output>', response_text, re.DOTALL)
            if match:
                json_str = match.group(1).strip()
                try:
                    structured_output = json.loads(json_str)
                    print("Successfully parsed JSON output.")
                    return {"status": "success", "output": structured_output}
                except json.JSONDecodeError as e:
                    print(f"JSON parsing error: {e}")
                    prompt += f"\n\nError: Invalid JSON format. Please ensure the output is valid JSON. Error: {e}\nInvalid JSON: {json_str}"
            else:
                print("No <json_output> tags found in LLM response.")
                prompt += "\n\nError: JSON output not enclosed in <json_output> tags. Please use the specified format."
        
        return {"status": "failure", "message": "Product Manager Agent failed to generate valid JSON after multiple attempts."}

if __name__ == "__main__":
    pm_agent = ProductManagerAgent()
    
    # Example 1: Simple feature request
    comment1 = "As a user, I want a dark mode toggle. It should save my preference. Priority: high."
    result1 = pm_agent.process_comment(comment1)
    print("\nResult 1:", json.dumps(result1, indent=2))

    # Example 2: More detailed feature request
    comment2 = """
    Feature: User Authentication
    Description: Implement a complete user authentication system including registration, login, and password reset functionalities. Users should be able to create accounts with email and password, log in securely, and reset forgotten passwords via email.
    Acceptance Criteria:
    - Users can register with a unique email and password.
    - Registered users can log in successfully.
    - Invalid credentials result in an error message.
    - Users can request a password reset email.
    - Password reset link in email allows users to set a new password.
    Priority: high
    """
    result2 = pm_agent.process_comment(comment2)
    print("\nResult 2:", json.dumps(result2, indent=2))

    # Example 3: Missing some details
    comment3 = "Add a 'contact us' form."
    result3 = pm_agent.process_comment(comment3)
    print("\nResult 3:", json.dumps(result3, indent=2))
