# Obscura Vault: Background Deployment & Autostart Guide

If you want the Obscura Vault to truly act as an autonomous background machine, you don't want to open a command prompt and type `python start.py` every time you restart your computer. 

Below are the instructions to make the software run **invisibly in the background** automatically as soon as you log into Windows.

---

## Method 1: The Invisible Startup Folder (Easiest)

This method uses a tiny Windows script to launch the Python server completely invisibly (no black terminal window) every time you turn on your computer.

### Step 1: Create the invisible launcher
1. Open Notepad.
2. Paste the following code into Notepad. **Important:** Change `C:\projects\obscure_vault` to the exact path where your Obscura Vault folder is located.

```vbs
Set WshShell = CreateObject("WScript.Shell")
' Change the path below to your actual project folder
WshShell.CurrentDirectory = "C:\projects\obscure_vault"
' Run pythonw.exe (which runs Python silently without a terminal)
WshShell.Run "pythonw.exe start.py", 0, False
```

3. Save the file as `obscura_invisible.vbs` directly inside your `obscure_vault` folder.

### Step 2: Add it to Windows Startup
1. Press `Windows Key + R` on your keyboard to open the Run dialog.
2. Type `shell:startup` and press Enter. This opens the secret Windows Startup folder.
3. Go back to your `obscure_vault` folder, **Right-Click** the `obscura_invisible.vbs` file you just made, and select **Create shortcut**.
4. Drag that new shortcut into the Windows Startup folder you opened in step 2.

**That's it!** Now, whenever you turn on your computer, the Obscura Vault will start running silently in the background. You can access it anytime by opening a web browser and going to `http://localhost:5050`.

---

## Method 2: Using Windows Task Scheduler (Advanced)

If you want the app to run even if you aren't logged into a user account (like on a dedicated server PC), use Task Scheduler.

1. Open the Windows Start Menu, search for **Task Scheduler**, and open it.
2. On the right-side panel, click **Create Basic Task...**
3. Name it `Obscura Vault Server` and click Next.
4. For the Trigger, select **When the computer starts** and click Next.
5. For the Action, select **Start a program** and click Next.
6. In the **Program/script** box, type `pythonw`
7. In the **Add arguments (optional)** box, type `start.py`
8. In the **Start in (optional)** box, paste the exact path to your folder (e.g., `C:\projects\obscure_vault`).
9. Click Next, then check the box that says **"Open the Properties dialog for this task when I click Finish"** and click Finish.
10. In the window that pops up, check the box that says **"Run whether user is logged on or not"** and check **"Run with highest privileges"**.
11. Click OK. It will ask for your Windows password to save it.

---

## How to Stop the Invisible Server

Because the terminal window is hidden, you can't just press `Ctrl+C` or click the 'X' button to stop the software. 

To shut it down:
1. Press `Ctrl + Shift + Esc` to open the Windows **Task Manager**.
2. Go to the **Details** tab (or **Processes** tab).
3. Scroll down until you find `pythonw.exe` in the list.
4. Right-click `pythonw.exe` and select **End Task**.

*Note: If you have other invisible Python scripts running, this will close them too. Make sure you only close the one using memory!*
