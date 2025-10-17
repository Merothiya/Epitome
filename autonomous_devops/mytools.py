import os
import subprocess
from github import Github
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
import json
import requests

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")

class GithubAPI:
    def __init__(self, repo_name):
        token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError("Missing GITHUB_TOKEN environment variable.")
        self.github = Github(token)
        self.repo = self.github.get_repo(repo_name)

    def get_repo_content(self, path=""):
        if not self.repo:
            raise Exception("Repository not set. Call set_repo() first.")
        contents = self.repo.get_contents(path)
        files = {}
        if isinstance(contents, list):
            # It's a directory
            for content in contents:
                if content.type == "file":
                    files[content.path] = content.decoded_content.decode()
                elif content.type == "dir":
                    files.update(self.get_repo_content(content.path))
        else:
            # It's a single file
            content = contents
            if content.type == "file":
                files[content.path] = content.decoded_content.decode()
        return files

    def commit_file(self, branch, file_path, content, commit_message):
        try:
            contents = self.repo.get_contents(file_path, ref=branch)
            self.repo.update_file(contents.path, commit_message, content, contents.sha, branch=branch)
            print(f"✏️ Updated {file_path} in {branch}")
        except Exception as e:
            if "404" in str(e):
                self.repo.create_file(file_path, commit_message, content, branch=branch)
                print(f"🆕 Created {file_path} in {branch}")
            else:
                raise

    def create_pr(self, title, body, head, base="main"):
        existing_prs = self.repo.get_pulls(state="open", head=f"{self.repo.owner.login}:{head}")
        if existing_prs.totalCount > 0:
            print("⚠️ PR already exists for this branch, skipping creation.")
            return {"pr_url": existing_prs[0].html_url, "pr_number": existing_prs[0].number}
        if not any(b.name == head for b in self.repo.get_branches()):
            raise ValueError(f"Branch {head} not found in repo.")
        pr = self.repo.create_pull(title=title, body=body, head=head, base=base)
        print(f"🚀 Created PR #{pr.number}: {pr.html_url}")
        return {"pr_url": pr.html_url, "pr_number": pr.number}

    def create_branch(self, branch_name, base="main"):
        for ref in self.repo.get_git_refs():
            if ref.ref == f"refs/heads/{branch_name}":
                print("Branch exists, skipping creation")
                return branch_name
        base_ref = self.repo.get_git_ref(f"heads/{base}")
        self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_ref.object.sha)
        print(f"✅ Created branch {branch_name} from {base}")
        return branch_name

    def get_pr_diff(self, pr_number):
        if not self.repo:
            raise Exception("Repository not set. Call set_repo() first.")
        pr = self.repo.get_pull(pr_number)
        return requests.get(pr.diff_url).text

class SeleniumTester:
    def __init__(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    def run_tests(self, test_file_path):
        # Temporarily remove --html argument to resolve "unrecognized arguments" error.
        # If HTML reports are required, ensure pytest-html is installed in the environment.
        command = ["pytest", test_file_path]
        report_path = None # No HTML report generated with this change

        print("Running tests without HTML report generation (pytest-html plugin not used).")

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return {"success": True, "output": result.stdout, "report": report_path}
        except subprocess.CalledProcessError as e:
            return {"success": False, "output": e.stdout + e.stderr, "report": report_path}

    def deploy_and_test_ui(self, deploy_url, actions):
        try:
            self.driver.get(deploy_url)
            screenshots = []
            for action in actions:
                if action["type"] == "click":
                    self.driver.find_element(By.CSS_SELECTOR, action["selector"]).click()
                elif action["type"] == "type":
                    self.driver.find_element(By.CSS_SELECTOR, action["selector"]).send_keys(action["text"])
                # Add more actions as needed
                self.driver.save_screenshot(f"reports/screenshot_{len(screenshots)}.png")
                screenshots.append(f"reports/screenshot_{len(screenshots)}.png")
            return {"success": True, "screenshots": screenshots, "logs": self.driver.get_log("browser")}
        finally:
            self.driver.quit()

class RiskAnalyzer:
    def analyze_diff(self, commit_diff, repo_vector_memory):
        # Placeholder for Gemini-based risk analysis
        # In phase 1, this will be a mock or simple heuristic
        # Scale to 0-10 as per requirements
        risk_score = (len(commit_diff.splitlines()) / 100.0) * 10 # Simple heuristic, scaled
        return {"estimated_risk_score": min(risk_score, 10)} # Ensure it doesn't exceed 10

class CIManager:
    def deploy_to_vercel(self, project_path):
        # Placeholder for Vercel deployment
        print(f"Simulating Vercel deployment for {project_path}")
        return {"deploy_url": "http://localhost:3000", "status": "success"}

    def deploy_to_docker(self, project_path):
        # Placeholder for Docker deployment
        print(f"Simulating Docker deployment for {project_path}")
        return {"deploy_url": "http://localhost:3000", "status": "success"}

class MongoDBService:
    def __init__(self):
        from pymongo import MongoClient
        try:
            self.client = MongoClient(MONGO_URI)
            # The ismaster command is cheap and does not require auth.
            self.client.admin.command('ismaster')
            self.db = self.client["autonomous_devops_db"]
            print("MongoDB connection successful.")
        except Exception as e:
            print(f"MongoDB connection failed: {e}")
            self.client = None
            self.db = None

    def insert_log(self, collection_name, log_entry):
        if not self.db:
            return "MongoDB not connected. Log insertion skipped."
        try:
            collection = self.db[collection_name]
            collection.insert_one(log_entry)
            print(f"Log inserted into {collection_name}: {log_entry}")
            return f"Log inserted into {collection_name}"
        except Exception as e:
            print(f"Error inserting log into {collection_name}: {e}")
            return f"Error inserting log into {collection_name}: {e}"

    def get_logs(self, collection_name, query={}):
        if not self.db:
            return []
        try:
            collection = self.db[collection_name]
            return list(collection.find(query))
        except Exception as e:
            print(f"Error retrieving logs from {collection_name}: {e}")
            return []
