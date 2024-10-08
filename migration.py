import os
import shutil
import subprocess
import stat
from github import Github
import csv
import time

# GitHub Personal Access Token from environment variable
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

if not GITHUB_TOKEN:
    raise ValueError("GITHUB_TOKEN environment variable not set.")

# Initialize GitHub connection
g = Github(GITHUB_TOKEN)

# GitHub repo where the CI templates are stored
CI_TEMPLATE_REPO = "capgemini-ga-demo/github_centralized_workflows"
CI_TEMPLATE_BRANCH = "develop"
CI_TEMPLATE_PATH = "templates"

# CSV file paths
source_repos_file = "source_repos.csv"
target_repos_file = "target_repos.csv"
csv_file_path = "migration_summary.csv"

# Build system file indicators
build_systems = {
    'maven': 'pom.xml',
    'gradle': 'build.gradle',
    'npm': 'package.json',
    'yarn': 'yarn.lock',
    'make': 'Makefile',
    'cmake': 'CMakeLists.txt',
    'bazel': 'BUILD',
    'go': 'go.mod',
    'rust': 'Cargo.toml',
    'python_setuptools': 'setup.py',
    'python_pip': 'requirements.txt',
    'python_pyproject': 'pyproject.toml',
    'ruby_bundler': 'Gemfile',
    'ruby_gem': '.gemspec',
    'dotNET_CS': '.csproj',
    'dotNET_VB': '.vbproj',
    'dotNET_FS': '.fsproj',
    'dotNET_Solution': '.sln',
    'dotNET_SDK': 'global.json',
    'dotNET_NuGet': 'packages.config'
}

def print_separator_with_repo_name(repo_name, phase="Starting migration"):
    """Prints a separator line with the repo_name in the middle."""
    total_length = 100  # Total length of the line including equal signs and repo_name
    repo_display = f" {phase} for {repo_name} "  # Add spaces for padding around repo_name
    num_equals = total_length - len(repo_display)
    
    left_equals = num_equals // 2
    right_equals = num_equals - left_equals
    
    print(f"\n{'=' * left_equals}{repo_display}{'=' * right_equals}\n")

def detect_language_and_build_system(repo_name):
    """Detect the primary language and the build system used in a GitHub repository."""
    try:
        repo = g.get_repo(repo_name)
        primary_language = repo.language

        contents = repo.get_contents("")
        repo_files = [content.path for content in contents]
        
        detected_build_systems = []
        for build_system, indicator_file in build_systems.items():
            if any(indicator_file in file for file in repo_files):
                detected_build_systems.append(build_system)
        
        build_systems_detected = ', '.join(detected_build_systems) if detected_build_systems else "No common build system detected."

        return primary_language, build_systems_detected
    except Exception as e:
        print(f"Error fetching repository data for {repo_name}: {e}")
        return None, None

def load_repositories_from_file(file_path):
    """Read repository names from a file."""
    try:
        with open(file_path, "r") as file:
            return [line.strip() for line in file if line.strip()]
    except Exception as e:
        print(f"Error reading the file: {e}")
        return []

def fetch_ci_file_from_github(build_system):
    """Fetch the CI template from the Centralized Workflow repository."""
    try:
        repo = g.get_repo(CI_TEMPLATE_REPO)
        ci_file_path = f"{CI_TEMPLATE_PATH}/{build_system}-ci.yml"

        # Fetch the content if the file exists
        ci_file = repo.get_contents(ci_file_path, ref=CI_TEMPLATE_BRANCH)
        return ci_file.decoded_content.decode('utf-8')
    
    except Exception as e:
        print(f"Error fetching Centralized Workflow File for {build_system}: {e}")
        return None

def create_or_update_repo(target_repo):
    """Create or update the target repository if it doesn't exist."""
    org_name, repo_name = target_repo.split('/')
    try:
        org = g.get_organization(org_name)
        repo = org.get_repo(repo_name)
        print(f"Repository '{repo_name}' already exists in the target organization '{org_name}'.")
        return repo
    except Exception:
        try:
            print(f"Creating repository '{repo_name}' in the organization '{org_name}'...")
            repo = g.get_organization(org_name).create_repo(repo_name)
            print(f"\033[92mRepository '{repo.name}' created successfully.\033[0m")
            return repo
        except Exception as e:
            print(f"Error creating repository '{repo_name}' in organization '{org_name}': {e}")
            return None

def push_branches_and_tags(local_repo_path, target_repo):
    """Push the branches and tags to the target repository."""
    try:
        subprocess.run(['git', 'remote', 'rm', 'origin'], cwd=local_repo_path, check=True)

        # Create or update target repo before pushing
        repo = create_or_update_repo(target_repo)

        if repo is None:
            print(f"Failed to create or update target repository: {target_repo}. Aborting push.")
            return

        push_url = f'https://github.com/{target_repo}.git'

        subprocess.run(['git', 'remote', 'add', 'origin', push_url], cwd=local_repo_path, check=True)

        print(f"  - Pushing branches and tags to '{push_url}'...")
        subprocess.run(['git', 'push', '--all'], cwd=local_repo_path, check=True)  # Push all branches
        subprocess.run(['git', 'push', '--tags'], cwd=local_repo_path, check=True)  # Push all tags

    except subprocess.CalledProcessError as e:
        print(f"Error pushing branches and tags: {e}")

def log_migration_to_csv(source_url, target_url, migrated_with_workflow):
    """Log migration details to a CSV file without creating duplicate entries."""
    file_exists = os.path.isfile(csv_file_path)

    existing_entries = []
    if file_exists:
        with open(csv_file_path, mode='r', newline='') as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                existing_entries.append(row['source_github_url'])

    if source_url not in existing_entries:
        with open(csv_file_path, mode='a', newline='') as csv_file:
            fieldnames = ['source_github_url', 'target_github_url', 'migrated_with_workflow_file']
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            writer.writerow({
                'source_github_url': source_url,
                'target_github_url': target_url,
                'migrated_with_workflow_file': migrated_with_workflow
            })
        print(f"Logged migration for {source_url} to {target_url}.")
    else:
        print(f"Duplicate entry detected for {source_url}. Skipping logging.")

# Helper function to remove read-only permission before deleting files
def remove_readonly(func, path, exc_info):
    """Change the file to writable before trying to delete it."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def cleanup_directory(directory_path):
    """Clean up a directory, ensuring all files are writable before deleting."""
    try:
        print(f"  - Cleaning up {directory_path}")
        shutil.rmtree(directory_path, onerror=remove_readonly)
    except Exception as e:
        print(f"  - Error cleaning up {directory_path}: {e}")

if __name__ == "__main__":
    # Load source and target repositories
    source_repos = load_repositories_from_file(source_repos_file)
    target_repos = load_repositories_from_file(target_repos_file)
    
    if not source_repos or not target_repos:
        print("No repositories found in the input files.")
    elif len(source_repos) != len(target_repos):
        print("Mismatch between the number of source and target repositories.")
    else:
        for source_repo, target_repo in zip(source_repos, target_repos):
            print_separator_with_repo_name(source_repo, phase="Starting migration")

            primary_language, build_system = detect_language_and_build_system(source_repo)
            if primary_language and build_system:
                print(f"Source Repository: {source_repo}")
                print(f"  - Primary Language: {primary_language}")
                print(f"  - Build System(s): {build_system}")
                
                # Clone the source repository
                local_repo_name = source_repo.split('/')[-1]
                local_repo_path = os.path.join(os.getcwd(), f"{local_repo_name}-repo")

                if os.path.exists(local_repo_path):
                    print(f"  - Directory '{local_repo_name}-repo' already exists. Removing it.")
                    shutil.rmtree(local_repo_path, onerror=remove_readonly)

                print(f"  - Cloning the source repository as a mirror to '{local_repo_name}-repo'...")
                subprocess.run(['git', 'clone', '--mirror', f'https://github.com/{source_repo}.git', local_repo_path], check=True)

                temporary_work_dir = os.path.join(os.getcwd(), f"{local_repo_name}-worktree")
                if os.path.exists(temporary_work_dir):
                    print(f"  - Temporary worktree directory '{temporary_work_dir}' already exists. Removing it.")
                    shutil.rmtree(temporary_work_dir)

                subprocess.run(['git', 'clone', local_repo_path, temporary_work_dir], check=True)

                # Optionally fetch CI file and commit it
                build_system_list = build_system.split(', ')  
                ci_found = False
                ci_content = None
                for system in build_system_list:
                    ci_content = fetch_ci_file_from_github(system.strip())
                    if ci_content:
                        ci_found = True
                        print(f"\033[92m  - Centralized Workflow File Found for {system.strip()} from Centralized Workflow Repository\033[0m")
                        break
                    else:
                        print(f"\033[91m  - Centralized Workflow File {system.strip()}-ci.yml does not exist in Centralized Workflow Repository.\033[0m")

                if ci_found and ci_content:
                    print(f"  - Saving Centralized Workflow File to '{temporary_work_dir}/.github/workflows/'...")
                    workflow_dir = os.path.join(temporary_work_dir, '.github', 'workflows')
                    os.makedirs(workflow_dir, exist_ok=True)
                    ci_file_path = os.path.join(workflow_dir, f"{system.strip()}-ci.yml")
                    with open(ci_file_path, 'w') as ci_file:
                        ci_file.write(ci_content)

                    try:
                        print(f"  - Committing and pushing the CI file for {local_repo_name}...")
                        subprocess.run(['git', 'add', '.'], cwd=temporary_work_dir, check=True)
                        subprocess.run(['git', 'commit', '-m', 'Added CI workflow file'], cwd=temporary_work_dir, check=True)
                        subprocess.run(['git', 'push', 'origin', 'main'], cwd=temporary_work_dir, check=True)
                        print(f"\033[92m  - CI file pushed successfully.\033[0m")
                    except subprocess.CalledProcessError as e:
                        print(f"\033[91m  - Error committing or pushing the CI file: {e}\033[0m")

                # Push branches and tags to the target repository
                push_branches_and_tags(local_repo_path, target_repo)

                time.sleep(10)

                # Log migration details
                source_url = f'https://github.com/{source_repo}.git'
                log_migration_to_csv(source_url, f'https://github.com/{target_repo}.git', ci_found)

                # Run garbage collection to release any locks before cleanup
                subprocess.run(['git', 'gc'], cwd=temporary_work_dir, check=True)

                # Clean up local mirrored repository
                cleanup_directory(local_repo_path)

                # Clean up temporary working directory
                cleanup_directory(temporary_work_dir)

                print(f"\033[92m  - Migration complete for repository: {source_repo}\033[0m")
            else:
                print(f"\033[91mCould not determine the language or build system for repository: {source_repo}\033[0m")

            print_separator_with_repo_name(source_repo, phase="End of migration")
