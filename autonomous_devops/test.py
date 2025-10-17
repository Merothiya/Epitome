from github import Github
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

load_dotenv()

REPO_NAME = "Merothiya/Snakes-Ladders-and-Faith" # Corrected GitHub repository name

github_api = GithubAPI(repo_name=REPO_NAME)
print(github_api.repo.full_name)  # Should print Merothiya/Snakes-Ladders-and-Faith
print(github_api.repo.owner.login)  # Should print Merothiya

gh = Github(os.environ["GITHUB_TOKEN"])
print(gh.get_user().login)
