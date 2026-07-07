<div align="center">

<a href="https://github.com/zhixiangxue/rume"><img src="https://raw.githubusercontent.com/zhixiangxue/rume/main/docs/assets/logo.png" alt="RUME Logo" width="120"></a>

[![Python Version](https://img.shields.io/pypi/pyversions/rume)](https://pypi.org/project/rume/)
[![License](https://img.shields.io/github/license/zhixiangxue/rume)](https://github.com/zhixiangxue/rume/blob/main/LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/zhixiangxue/rume?style=social)](https://github.com/zhixiangxue/rume)

**RUME** gets any system running from a single prompt — GitHub repos, local folders, one service or ten.

</div>

---

```bash
rume "Get https://github.com/user/repo running on my machine" --model deepseek/deepseek-chat --api-key sk-xxx
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/zhixiangxue/rume/main/install.sh | bash
```

Python 3.12+ is all you need.

---

## Use

```bash
# GitHub URL or local path — same thing
rume "Get https://github.com/user/backend running on port 8080" \
  --model deepseek/deepseek-chat \
  --api-key sk-your-key-here

rume "Start /Users/me/projects/my-app in dev mode" \
  --model openai/gpt-4o \
  --api-key sk-your-key-here

# Multiple services, one prompt
rume "Backend: https://github.com/org/api (port 8080)
       Frontend: https://github.com/org/web (port 3000, needs backend)" \
  --model anthropic/claude-sonnet-4-6 \
  --api-key sk-your-key-here

# No idea how to run it? Let rume figure it out
rume "Go explore https://github.com/user/mystery-repo and get it running" \
  --model deepseek/deepseek-chat \
  --api-key sk-your-key-here
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

<div align="right"><a href="https://github.com/zhixiangxue/rume"><img src="https://raw.githubusercontent.com/zhixiangxue/rume/main/docs/assets/logo.png" alt="RUME Logo" width="80"></a></div>
