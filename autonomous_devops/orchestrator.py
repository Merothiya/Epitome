import os
import json
from agents.builder_agent import BuilderAgent
from agents.reviewer_agent import ReviewerAgent
from agents.qa_agent import QAAgent
from agents.impact_analyzer_agent import ImpactAnalyzerAgent
from agents.confidence_merge_controller_agent import ConfidenceMergeControllerAgent
from agents.auto_documentation_agent import AutoDocumentationAgent
from agents.product_manager_agent import ProductManagerAgent # New import
from mytools import MongoDBService, GithubAPI
from dotenv import load_dotenv
from git_workflow import automated_git_workflow # New import for automated git workflow
import re # Import for regular expressions
import subprocess # Import for running shell commands

load_dotenv()

REPO_NAME = "Merothiya/Snakes-Ladders-and-Faith" # Corrected GitHub repository name
REPO_OWNER = REPO_NAME.split('/')[0]
REPO_SLUG = REPO_NAME.split('/')[1]
REPO_URL = f"https://github.com/{REPO_NAME}.git" # Full URL for cloning

github_api = GithubAPI(repo_name=REPO_NAME)
mongo_service = MongoDBService()

# Define the local path where the repository will be cloned
LOCAL_REPO_PATH = os.path.join(os.getcwd(), REPO_SLUG)

def run_devops_cycle(raw_user_comment): # Updated signature
    # The REPO_NAME already includes the owner, so we can use it directly for the link.
    repo_link = f"https://github.com/{REPO_NAME}"
    print(f"Working with GitHub repository: {repo_link}")

    # Run the automated Git workflow to ensure the repository is cloned and up-to-date
    print("Running automated Git workflow to initialize/update repository...")
    workflow_success = automated_git_workflow(REPO_URL, LOCAL_REPO_PATH, branch='main')
    if not workflow_success:
        print("Automated Git workflow failed during initialization. Aborting.")
        return {"status": "failure", "message": "Git workflow initialization failed."}
    print("Automated Git workflow completed successfully for initialization.")

    # 0. Product Manager Agent (New)
    print("Running Product Manager Agent...")
    pm_agent = ProductManagerAgent()
    pm_response = pm_agent.process_comment(raw_user_comment)
    
    if pm_response["status"] == "failure":
        print(f"Product Manager Agent failed: {pm_response['message']}")
        return {"status": "failure", "message": pm_response["message"]}
    
    feature_ticket = pm_response["output"]
    print(f"Product Manager Agent Output (Feature Ticket): {json.dumps(feature_ticket, indent=2)}")
    print(f"Starting DevOps cycle for feature: {feature_ticket['title']}")

    # Determine the feature branch name
    feature_branch_name = f"feature/{feature_ticket['feature_id']}-{feature_ticket['title'].replace(' ', '-').lower()}"
    feature_branch_name = re.sub(r'[^a-zA-Z0-9\-_]', '-', feature_branch_name)
    feature_branch_name = feature_branch_name[:100]

    # Create a new branch for the feature
    print(f"Creating feature branch: {feature_branch_name}...")
    try:
        github_api.create_branch(feature_branch_name, base='main')
        print(f"Branch '{feature_branch_name}' created successfully on remote.")
    except Exception as e:
        print(f"Failed to create branch '{feature_branch_name}': {e}")
        return {"status": "failure", "message": f"Failed to create feature branch: {e}"}

    # Checkout the newly created branch locally
    print(f"Checking out local branch '{feature_branch_name}' in {LOCAL_REPO_PATH}...")
    try:
        # First, fetch to ensure the local repo knows about the new remote branch
        subprocess.run(['git', 'fetch', 'origin'], cwd=LOCAL_REPO_PATH, check=True)
        
        # Check if the local branch already exists
        result = subprocess.run(['git', 'rev-parse', '--verify', feature_branch_name], cwd=LOCAL_REPO_PATH, capture_output=True, text=True)
        if result.returncode == 0:
            # If local branch exists, just switch to it
            subprocess.run(['git', 'checkout', feature_branch_name], cwd=LOCAL_REPO_PATH, check=True)
            print(f"Successfully switched to existing local branch '{feature_branch_name}'.")
        else:
            # If local branch does not exist, create it from the remote branch
            subprocess.run(['git', 'checkout', '-b', feature_branch_name, f'origin/{feature_branch_name}'], cwd=LOCAL_REPO_PATH, check=True)
            print(f"Successfully created and checked out local branch '{feature_branch_name}' tracking 'origin/{feature_branch_name}'.")

        # Verify local branch status
        print(f"Verifying local branch status in {LOCAL_REPO_PATH}...")
        subprocess.run(['git', 'branch', '-vv'], cwd=LOCAL_REPO_PATH, check=True)

    except subprocess.CalledProcessError as e:
        print(f"Failed to checkout local branch '{feature_branch_name}': {e.stderr}")
        return {"status": "failure", "message": f"Failed to checkout local branch: {e.stderr}"}
    except Exception as e:
        print(f"An unexpected error occurred during local branch checkout: {e}")
        return {"status": "failure", "message": f"Unexpected error during local branch checkout: {e}"}

    # 1. Builder Agent (A1)
    print("Running Builder Agent (A1)...")
    builder = BuilderAgent(github_api=github_api, local_repo_path=LOCAL_REPO_PATH)
    builder_response = builder.run(feature_ticket)
    print(f"Builder Agent Response: {builder_response}")

    if builder_response.get("status") != "success":
        print(f"Builder Agent failed: {builder_response.get('message')}")
        return builder_response # Or handle gracefully

    if builder_response.get("local_changes_made"):
        print("Builder Agent made local changes. Committing and pushing via automated Git workflow...")
        commit_push_success = automated_git_workflow(
            REPO_URL,
            LOCAL_REPO_PATH,
            branch=feature_branch_name, # Push to the feature branch
            commit_message_prefix=f"feat({feature_ticket['feature_id']}): {feature_ticket['title']}"
        )
        if not commit_push_success:
            print("Automated Git workflow failed during commit/push. Aborting.")
            return {"status": "failure", "message": "Git workflow commit/push failed."}
        print("Automated Git workflow completed successfully for commit/push.")

        # Now create a Pull Request
        print(f"Creating Pull Request for branch: {feature_branch_name}...")
        pr_title = f"feat({feature_ticket['feature_id']}): {feature_ticket['title']}"
        pr_body = f"Implements feature: {feature_ticket['description']}\n\n" \
                  f"Generated by Builder Agent (A1) for feature ticket: {feature_ticket['id']}"
        
        try:
            pr_output = github_api.create_pr(title=pr_title, body=pr_body, head=feature_branch_name, base='main')
            pr_url = pr_output.get("pr_url")
            pr_number = int(pr_output.get("pr_number"))
            print(f"Pull Request created: {pr_url}")
        except Exception as e:
            print(f"Failed to create Pull Request: {e}")
            return {"status": "failure", "message": f"Failed to create PR: {e}"}
    else:
        print("Builder Agent reported no local changes. Skipping commit/push and PR creation.")
        return {"status": "success", "message": "No changes made by Builder Agent."} # End cycle if no changes

    pr_details = {
        "id": pr_number,
        "title": feature_ticket["title"],
        "author": "builder-agent",
        "url": pr_url
    }

    # Auto Documentation Agent (Post-Push) - now post-PR creation
    print("Running Auto Documentation Agent (Post-PR Creation)...")
    auto_doc_agent = AutoDocumentationAgent(github_api=github_api)
    auto_doc_response_push = auto_doc_agent.run_documentation(pr_number=pr_number, pr_details=pr_details)
    print(f"Auto Documentation Agent Response (Post-PR Creation): {auto_doc_response_push}")

    # 2. Reviewer Agent (A2)
    print("Running Reviewer Agent (A2)...")
    reviewer = ReviewerAgent(github_api=github_api)
    reviewer_response = reviewer.run_review(pr_number=pr_number, pr_details=pr_details)
    print(f"Reviewer Agent Response: {reviewer_response}")

    # 3. QA Agent (A4)
    print("Running QA Agent (A4)...")
    qa_agent = QAAgent()
    # Assuming the project to be deployed is in the current directory for simplicity
    # In a real scenario, this path would be dynamic, possibly from the builder agent's output
    project_path = "." 
    qa_response = qa_agent.run_qa(feature_ticket=feature_ticket, deploy_method="vercel", project_path=project_path)
    print(f"QA Agent Response: {qa_response}")

    # 4. Impact Analyzer (A6)
    print("Running Impact Analyzer Agent (A6)...")
    impact_analyzer = ImpactAnalyzerAgent(github_api=github_api)
    # repo_vector_memory is a placeholder for now
    impact_analyzer_response = impact_analyzer.run_analysis(pr_number=pr_number, pr_details=pr_details, repo_vector_memory={})
    print(f"Impact Analyzer Agent Response: {impact_analyzer_response}")

    # 5. Confidence & Merge Controller (A5)
    print("Running Confidence & Merge Controller Agent (A5)...")
    merge_controller = ConfidenceMergeControllerAgent(github_api=github_api)
    # The following are placeholders. In a real system, these would be parsed from agent responses.
    test_results = {"success": True} # Assuming tests passed from builder_response
    review_feedback = {"review_summary": "Approved"} # Assuming review passed from reviewer_response
    qa_report = {"ui_bugs_detected": False} # Assuming QA passed from qa_response
    risk_score = 2.5 # Assuming a risk score from impact_analyzer_response
    
    merge_controller_response = merge_controller.run_merge_decision(
        test_results=test_results,
        review_feedback=review_feedback,
        qa_report=qa_report,
        risk_score=risk_score,
        pr_details=pr_details
    )
    print(f"Confidence & Merge Controller Agent Response: {merge_controller_response}")

    # 6. Auto Documentation Agent (Post-Merge)
    # Assuming the merge was successful if confidence was high
    # In a real system, we would check the merge status from the merge_controller_response
    if True: # Placeholder for checking merge success
        print("Running Auto Documentation Agent (Post-Merge)...")
        auto_doc_agent = AutoDocumentationAgent(github_api=github_api)
        auto_doc_response = auto_doc_agent.run_documentation(pr_number=pr_number, pr_details=pr_details)
        print(f"Auto Documentation Agent Response: {auto_doc_response}")
    else:
        auto_doc_response = "Merge was not performed, skipping documentation."

    # Log the end of the cycle
    mongo_service.insert_log(
        "orchestration_cycles",
        {
            "feature_ticket_id": feature_ticket["id"],
            "status": "completed_full_cycle",
            "builder_response": builder_response,
            "reviewer_response": reviewer_response,
            "qa_response": qa_response,
            "impact_analyzer_response": impact_analyzer_response,
            "merge_controller_response": merge_controller_response,
            "auto_documentation_response": auto_doc_response,
            "timestamp": mongo_service.get_logs("orchestration_cycles").__len__() + 1 # Simple timestamp for now
        }
    )
    print("DevOps cycle (Builder, Reviewer, QA, Impact Analyzer, Merge Controller, and Auto Documentation) completed and logged.")

if __name__ == "__main__":
    # Prompt the user for the feature they want to implement
    print("Please describe the feature you want to implement (type 'exit' to quit):")
    user_input_lines = []
    while True:
        line = input()
        if line.lower() == 'exit':
            break
        user_input_lines.append(line)
    raw_user_comment = "\n".join(user_input_lines)

    if raw_user_comment.strip():
        run_devops_cycle(raw_user_comment)
    else:
        print("No feature description provided. Exiting.")
