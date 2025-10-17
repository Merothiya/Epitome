import subprocess
import os
import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_command(command, cwd=None, check_error=True):
    """
    Runs a shell command and handles errors.
    """
    try:
        logging.info(f"Executing command: {' '.join(command)}")
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=check_error)
        if result.stdout:
            logging.info(f"Command output:\n{result.stdout}")
        if result.stderr and check_error:
            logging.error(f"Command error:\n{result.stderr}")
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed with error code {e.returncode}:\n{e.stderr}")
        raise
    except FileNotFoundError:
        logging.error(f"Command not found: {command[0]}. Make sure Git is installed and in your PATH.")
        raise

def clone_repository(repo_url, local_path, branch='main'):
    """
    Clones a Git repository if it doesn't exist locally.
    """
    if os.path.exists(local_path) and os.path.isdir(local_path):
        logging.info(f"Repository already exists at {local_path}. Skipping clone.")
        return True
    
    logging.info(f"Cloning repository {repo_url} into {local_path}...")
    try:
        run_command(['git', 'clone', '-b', branch, repo_url, local_path], check_error=True)
        logging.info("Repository cloned successfully.")
        return True
    except Exception:
        logging.error(f"Failed to clone repository {repo_url}.")
        return False

def detect_changes(local_path):
    """
    Detects changes in the local project files.
    Returns True if changes are detected, False otherwise.
    """
    logging.info(f"Detecting changes in {local_path}...")
    try:
        result = run_command(['git', 'status', '--porcelain'], cwd=local_path, check_error=True)
        if result.stdout.strip():
            logging.info("Changes detected.")
            return True
        else:
            logging.info("No changes detected.")
            return False
    except Exception:
        logging.error("Failed to detect changes.")
        return False

def apply_changes(local_path):
    """
    Placeholder for applying changes. In a real scenario, this would involve
    your application logic modifying files.
    For this workflow, we assume changes are already made by other processes.
    """
    logging.info(f"Applying changes in {local_path} (assuming changes are already made by other processes).")
    # This function is a placeholder. Actual changes would be made by other parts of the system.
    pass

def verify_changes(local_path):
    """
    Verifies the changes (e.g., runs tests or validation scripts).
    Returns True if verification passes, False otherwise.
    """
    logging.info(f"Verifying changes in {local_path}...")
    # Placeholder for running tests or validation scripts
    # Example: if os.path.exists(os.path.join(local_path, 'run_tests.sh')):
    #              run_command(['bash', 'run_tests.sh'], cwd=local_path)
    logging.info("Verification step completed (no actual tests run in this example).")
    return True # Assume success for now

def stage_changes(local_path):
    """
    Stages all changes in the local repository.
    """
    logging.info(f"Staging all changes in {local_path}...")
    try:
        run_command(['git', 'add', '.'], cwd=local_path, check_error=True)
        logging.info("All changes staged successfully.")
        return True
    except Exception:
        logging.error("Failed to stage changes.")
        return False

def commit_changes(local_path, message_prefix="Automated commit"):
    """
    Commits changes with a descriptive message, including a timestamp.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    commit_message = f"{message_prefix} - {timestamp}"
    logging.info(f"Committing changes with message: '{commit_message}' in {local_path}...")
    try:
        run_command(['git', 'commit', '-m', commit_message], cwd=local_path, check_error=True)
        logging.info("Changes committed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        if "nothing to commit" in e.stderr:
            logging.info("No changes to commit.")
            return True # No changes to commit is not an error for this workflow
        logging.error(f"Failed to commit changes: {e.stderr}")
        return False
    except Exception:
        logging.error("Failed to commit changes.")
        return False

def push_changes(local_path, remote='origin', branch='main'):
    """
    Pushes the commits to the remote repository automatically.
    Handles potential merge conflicts by attempting a pull before push.
    """
    logging.info(f"Pushing changes to {remote}/{branch} from {local_path}...")
    try:
        # Attempt to pull before pushing to avoid simple conflicts
        logging.info("Attempting to pull latest changes before pushing...")
        run_command(['git', 'pull', remote, branch], cwd=local_path, check_error=True)
        logging.info("Pull successful.")
        
        run_command(['git', 'push', remote, branch], cwd=local_path, check_error=True)
        logging.info("Changes pushed successfully.")
        return True
    except subprocess.CalledProcessError as e:
        if "Updates were rejected because the remote contains work that you do not have locally" in e.stderr:
            logging.error("Push rejected due to remote changes. Manual intervention might be needed for merge conflicts.")
        else:
            logging.error(f"Failed to push changes: {e.stderr}")
        return False
    except Exception:
        logging.error("Failed to push changes.")
        return False

def automated_git_workflow(repo_url, local_path, branch='main', commit_message_prefix="Automated commit"):
    """
    Main function to run the automated Git workflow.
    """
    logging.info(f"Starting automated Git workflow for {repo_url} (branch: {branch}) at {local_path}")

    # 1. Clone repository
    if not clone_repository(repo_url, local_path, branch):
        return False

    # 2. Apply changes (placeholder)
    apply_changes(local_path)

    # 3. Detect changes
    if not detect_changes(local_path):
        logging.info("No changes to process. Workflow finished.")
        return True

    # 4. Verify changes
    if not verify_changes(local_path):
        logging.error("Changes verification failed. Aborting workflow.")
        return False

    # 5. Stage all changes
    if not stage_changes(local_path):
        logging.error("Failed to stage changes. Aborting workflow.")
        return False

    # 6. Commit changes
    if not commit_changes(local_path, commit_message_prefix):
        logging.error("Failed to commit changes. Aborting workflow.")
        return False

    # 7. Push commits
    if not push_changes(local_path, branch=branch):
        logging.error("Failed to push changes. Aborting workflow.")
        return False

    logging.info("Automated Git workflow completed successfully.")
    return True

if __name__ == "__main__":
    # Example Usage:
    # Replace with your actual repository URL and local path
    REPO_URL = "https://github.com/your-username/your-repo.git" # IMPORTANT: Change this
    LOCAL_REPO_PATH = "my_cloned_repo" # IMPORTANT: Change this
    BRANCH = "main" # Or your desired branch

    # Create the local_repo_path relative to the current working directory
    full_local_path = os.path.join(os.getcwd(), LOCAL_REPO_PATH)

    logging.info(f"Current working directory: {os.getcwd()}")
    logging.info(f"Full local repository path: {full_local_path}")

    # To test, you might need to create a dummy change in 'my_cloned_repo'
    # For example:
    # with open(os.path.join(full_local_path, 'test_file.txt'), 'a') as f:
    #     f.write(f"Test change at {datetime.datetime.now()}\n")

    # Run the workflow
    success = automated_git_workflow(REPO_URL, full_local_path, BRANCH)

    if success:
        logging.info("Workflow executed successfully.")
    else:
        logging.error("Workflow failed.")

    logging.info("Remember to replace REPO_URL and LOCAL_REPO_PATH with your actual values.")
    logging.info("For scheduling, you can run this script using cron (Linux/macOS) or Task Scheduler (Windows).")
