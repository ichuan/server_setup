Quickly setup a ubuntu server

## Environment and Tune
+ ichuan/dotfiles
+ limits.conf
+ UTC timezone

## Softwares Included
+ git
+ utils(zip, unzip, unrar, curl, wget, tar)
+ letsencrypt
+ nodejs
+ yarn
+ python-pip
+ python-virtualenv
+ sqlite3
+ tmux
+ ntp
+ build-essential
+ pillow reqs
+ uwsgi
+ nginx


## Optional Softwares
+ MySQL(root/root)
+ mongodb


## Usage

```shell
# basic setup (env and default softwares)
fab -H host1 setup
# setup env
fab -H host1 setup:env
# setup specific software(s)
fab -H host1 setup:mysql
fab -H host1 setup:nodejs,mysql
```
