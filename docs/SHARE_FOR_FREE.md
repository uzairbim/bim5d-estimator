# Share it for free

The code is MIT licensed and the data is public domain (CC0), so anyone can use, copy and share it.
Here are the free ways to give people access.

## 1. Everyone runs it on their own computer (simplest, private)

Send the zip. Each person:

- **Windows**: install Python 3.10+ from python.org (tick "Add python.exe to PATH"), unzip, double-click
  `start-windows.bat`. The first start installs everything (a few minutes); after that it opens in seconds.
- **Mac / Linux**: `bash start-mac-linux.sh`.

The browser opens at http://localhost:8000. Models and prices stay on that computer.
No Node.js, no database server, no account needed.

## 2. One free website for your team or the public (Hugging Face Spaces)

1. Create a free account at huggingface.co and click **New Space**.
2. Choose **Docker** as the SDK, visibility Public or Private.
3. Upload all project files (or connect a GitHub repository).
4. Add this block at the top of `README.md` of the Space:

   ```
   ---
   title: BIM 5D Estimator
   sdk: docker
   app_port: 8000
   ---
   ```

5. The Space builds the Dockerfile and gives you a link to share.

Notes: free Spaces sleep after a period without visitors and do not keep uploaded files when they
restart, so treat it as a demo. Download your Excel and rate packs. For a permanent team server, use
option 3.

## 3. Your own server (company network or a small cloud server)

```bash
docker compose up -d --build
```

The `projects/` and `data/` folders are mounted as volumes, so projects and prices survive updates.

## 4. GitHub (so others can contribute)

Create a public repository and push the folder. People can then:
- open issues for missing rules or wrong norms,
- send **rate packs** for their country (`Prices & rates → Region & sharing → Download rate pack`),
- add translations in `web/i18n.js`.

A good convention: put shared packs in `ratepacks/<COUNTRY>_<CITY>_<YYYY-MM>.json` with the source of
the prices written in the pack notes.

## Sharing prices safely

A rate pack contains the region settings and the prices you typed, nothing else (no models, no
project names). Check that you are allowed to share prices that came from supplier quotes.
