# Smart Attendance — MongoDB Atlas

This app stores attendance data in MongoDB Atlas in the `smart_attendance` database. Collections are created automatically when data is saved.

## Run locally (Windows PowerShell)
1. Install Python 3.10+.
2. Open this folder in PowerShell.
3. Install dependencies: `py -m pip install -r requirements.txt`
4. Verify `MONGODB_URI` in `.env`.
5. Check MongoDB Atlas connection: `py check_mongodb.py`
6. Start the server: `py server.py`
7. Open http://localhost:8000

The server loads `.env` automatically. The site loads directly with a modern web login screen (no browser popup).

### Default Administrator Credentials
- **Role**: Teacher / Admin
- **Username**: `admin`
- **Password**: `admin123`
*(You can also create custom teacher and student accounts directly from the login page!)*

## MongoDB Diagnostics & Health
- Run `py check_mongodb.py` anytime to verify Atlas connection, ping latency, cluster version, and read/write health.
- The web UI features a live **MongoDB Atlas status indicator** in the top navigation bar. Click it anytime to open real-time database diagnostics, document counts per collection, and latency metrics.

## MongoDB Atlas checklist
- Verify the database user under **Database Access**.
- Allow your current IP under **Network Access**.
- After saving attendance, browse the `smart_attendance` database in Atlas.
- Collections: `institutes`, `users`, `sections`, `subjects`, `students`, `schedule`, and `settings`.

## Deploy to Render
1. Push the project to a private GitHub repository.
2. Create a Render Blueprint from `render.yaml`.
3. Set `MONGODB_URI` and a strong `SITE_PASSWORD` in Render environment variables.
4. Deploy and open the HTTPS URL Render provides.

**Security:** `.env` is excluded by `.gitignore`; never commit or share it. Set a strong `SITE_PASSWORD` before public deployment. Browser-side app login checks are not a substitute for server-side role-based authentication.

**Credential warning:** The MongoDB connection string was shared in chat and should be treated as exposed. Rotate/reset the database user's password in Atlas, then update `MONGODB_URI` in `.env` and Render. Do not keep using the old password.
