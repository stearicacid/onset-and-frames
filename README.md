# MorishimaLabAscender

## What is MorishimaLabAscender?
A version of [Ascender](https://github.com/cvpaperchallenge-alumni/Ascender) customized for easy use with the Morishima Laboratory's computing environment

## Project Organization

```
    ├── .github/               <- GitHub settings.
    │
    ├── data/                  <- Datasets.
    │
    ├── environments/          <- Environment-specific configurations.
    │
    ├── models/                <- Pretrained and serialized models.
    │
    ├── outputs/               <- Outputs.
    │
    ├── src/                   <- Python Source code.
    │
    ├── .dockerignore
    ├── .gitignore
    ├── LICENSE
    ├── uv.lock                <- Auto-generated lock file.
    ├── pyproject.toml         <- Main project configuration file.
    └── README.md              <- Top-level README for developers.
```

## ✅ Environment Variable Setup

🔧 Save Host UID and GID

Create a script to detect and persist your user and group IDs:

```bash
id -u  # e.g., 1000
id -g  # e.g., 1000
echo $USER # e.g., sakaya
```

Edit your shell config file:

```bash
vim ~/.bash_profile  # Or ~/.bashrc, depending on your shell
```

Add the following lines:

```bash
# Addendum if there are none
if [ -f "$HOME/.bashrc" ]; then
    . "$HOME/.bashrc"
fi

# Be sure to add
export HOST_UID=1000  # Replace with output from id -u
export HOST_GID=1000  # Replace with output from id -g
export USER_NAME=sakaya # Replace with output from echo $USER
```

Apply changes:

```bash
source ~/.bash_profile
```
## Activate Docker Container

```bash
bash scripts/docker/a6000/1st.sh     # A6000 1st (LinuxのOSアプデが必要 -> アプデ後ダメだったらDockerfileをenvironments/A6000_1st_emergency/Dockerfile_1stemgに変更して試す)
bash scripts/docker/a6000/1st_emg.sh # A6000 1st (復旧するまではこっちを使用)
bash scripts/docker/a6000/2nd.sh     # A6000 2nd (LinuxのOSアプデが必要 -> アプデ後ダメだったらDockerfileをenvironments/A6000_1st_emergency/Dockerfile_1stemgに変更して試す)
bash scripts/docker/mic/mic.sh       # MicMachine
```

## If you want to change repogitory name...
You must also change `PROJECT_NAME_ENV` in all `environments/**/.envs` files.