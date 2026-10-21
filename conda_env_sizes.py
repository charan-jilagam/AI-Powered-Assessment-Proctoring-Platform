
# import os
# import subprocess
# from pathlib import Path


# def get_conda_envs():
#     """Get all Conda environment paths."""
#     result = subprocess.run(
#         ["conda", "env", "list", "--json"],
#         capture_output=True,
#         text=True,
#         check=True
#     )

#     import json
#     data = json.loads(result.stdout)
#     return data.get("envs", [])


# def get_folder_size(folder):
#     """Calculate total folder size in bytes."""
#     total_size = 0

#     for root, dirs, files in os.walk(folder, onerror=lambda e: None):
#         for file in files:
#             file_path = os.path.join(root, file)
#             try:
#                 total_size += os.path.getsize(file_path)
#             except (OSError, PermissionError):
#                 pass

#     return total_size


# def main():
#     environments = get_conda_envs()
#     results = []

#     print("Calculating Conda environment sizes...\n")

#     for env_path in environments:
#         path = Path(env_path)
#         print(f"Scanning: {path.name or path}")

#         size_bytes = get_folder_size(env_path)

#         results.append({
#             "name": path.name if path.name else "base",
#             "size_gb": size_bytes / (1024 ** 3),
#             "path": str(path)
#         })

#     results.sort(key=lambda x: x["size_gb"], reverse=True)

#     print("\n" + "=" * 95)
#     print(f"{'Environment':<25} {'Size (GB)':>12}  {'Path'}")
#     print("=" * 95)

#     for env in results:
#         print(
#             f"{env['name']:<25} "
#             f"{env['size_gb']:>12.2f}  "
#             f"{env['path']}"
#         )

#     print("=" * 95)

#     total = sum(env["size_gb"] for env in results)
#     print(f"Total environment folder sizes: {total:.2f} GB")


# if __name__ == "__main__":
#     main()



import os

directory = r"D:\AI-Powered-Assessment-Proctoring-Platform"
output_file = "all_files.txt"

with open(output_file, "w", encoding="utf-8") as f:
    for root, dirs, files in os.walk(directory):
        # Skip common unnecessary directories
        dirs[:] = [
            d for d in dirs
            if d not in {
                ".git", "__pycache__", ".venv",
                "venv", "node_modules"
            }
        ]

        for file in files:
            file_path = os.path.join(root, file)
            f.write(file_path + "\n")

print(f"File list saved to: {os.path.abspath(output_file)}")
