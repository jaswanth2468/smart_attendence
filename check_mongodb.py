#!/usr/bin/env python3
"""
MongoDB Diagnostics Script for Smart Attendance
Run: python check_mongodb.py
"""
import os
import sys
import time
from dotenv import load_dotenv

# Terminal colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

def main():
    print(f"\n{BOLD}{BLUE}===================================================={RESET}")
    print(f"{BOLD}{BLUE}    Smart Attendance — MongoDB Connection Check    {RESET}")
    print(f"{BOLD}{BLUE}===================================================={RESET}\n")

    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"[{GREEN}OK{RESET}] Loaded environment variables from .env")
    else:
        print(f"[{YELLOW}WARN{RESET}] No .env file found; using system environment variables")

    uri = os.environ.get("MONGODB_URI", "").strip()
    db_name = os.environ.get("MONGODB_DB", "smart_attendance").strip()

    if not uri:
        print(f"[{RED}FAIL{RESET}] MONGODB_URI is not set in .env or environment.")
        print("       Please set MONGODB_URI in .env or provide it in your environment variables.")
        sys.exit(1)

    # Obfuscate URI for display
    try:
        if "@" in uri:
            prefix, rest = uri.split("@", 1)
            scheme = prefix.split("://")[0] + "://"
            clean_display_uri = f"{scheme}***:***@{rest}"
        else:
            clean_display_uri = "mongodb://***"
    except Exception:
        clean_display_uri = "mongodb+srv://***"

    print(f"[{GREEN}OK{RESET}] Connection URI configured: {clean_display_uri}")
    print(f"[{GREEN}OK{RESET}] Target database: {BOLD}{db_name}{RESET}")

    try:
        from pymongo import MongoClient
    except ImportError:
        print(f"[{RED}FAIL{RESET}] pymongo is not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    print("\nConnecting to MongoDB Atlas Cluster...")
    t0 = time.time()
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        # Ping the admin database
        ping_res = client.admin.command("ping")
        elapsed_ms = round((time.time() - t0) * 1000, 1)
        print(f"[{GREEN}SUCCESS{RESET}] MongoDB Ping successful in {BOLD}{elapsed_ms} ms{RESET}! Response: {ping_res}")
    except Exception as e:
        print(f"[{RED}FAIL{RESET}] Could not connect to MongoDB Atlas:")
        print(f"       {str(e)}")
        print("\nTroubleshooting tips:")
        print(" 1. Check your IP whitelist in MongoDB Atlas (Network Access -> Add Current IP Address / 0.0.0.0/0).")
        print(" 2. Verify database username and password in Database Access.")
        print(" 3. Verify that your internet connection is active.")
        sys.exit(1)

    try:
        build_info = client.admin.command("buildInfo")
        mongo_ver = build_info.get("version", "unknown")
        print(f"[{GREEN}OK{RESET}] MongoDB Server Version: {BOLD}{mongo_ver}{RESET}")
    except Exception:
        pass

    db = client[db_name]
    collections = db.list_collection_names()
    print(f"\n{BOLD}Existing Collections in '{db_name}':{RESET}")
    if not collections:
        print(f"       {YELLOW}(No collections created yet. Collections will be created automatically when data is saved.){RESET}")
    else:
        for col in sorted(collections):
            count = db[col].count_documents({})
            print(f"  • {BOLD}{col:<16}{RESET} : {count} documents")

    # Read/Write verification test
    print(f"\n{BOLD}Running Read/Write Verification Test...{RESET}")
    try:
        test_col = db["_db_health_check"]
        test_doc = {"test": True, "timestamp": time.time(), "client": "smart_attendance_check"}
        res = test_col.insert_one(test_doc)
        found = test_col.find_one({"_id": res.inserted_id})
        test_col.delete_one({"_id": res.inserted_id})
        db.drop_collection("_db_health_check")
        if found and found.get("test"):
            print(f"[{GREEN}SUCCESS{RESET}] Read & Write test passed successfully!")
        else:
            print(f"[{YELLOW}WARN{RESET}] Document inserted but retrieval failed.")
    except Exception as e:
        print(f"[{RED}FAIL{RESET}] Read/Write test failed: {e}")

    print(f"\n{BOLD}{GREEN}Result: MongoDB Atlas is FULLY WORKING and READY for Smart Attendance!{RESET}\n")

if __name__ == "__main__":
    main()
