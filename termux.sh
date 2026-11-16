#!/data/data/com.termux/files/usr/bin/bash
# প্রথমবার চালালে সেটআপ হবে, পরে চালালে শুধু সমকাল ও কালের কণ্ঠ আপডেট হবে।
# (পুরো ব্লক {} এর ভেতরে, যাতে git pull এর সময় স্ক্রিপ্ট বদলে গেলেও সমস্যা না হয়)
{
set -e
DIR="$HOME/kofeed"

if [ ! -d "$DIR/.git" ]; then
  echo "== প্রথমবার সেটআপ =="
  pkg update -y
  pkg install -y python git
  pip install requests beautifulsoup4
  echo -n "GitHub username: "; read U
  echo -n "Repo name (খালি রাখলে kofeed): "; read R; R=${R:-kofeed}
  echo -n "GitHub token (লেখা দেখা যাবে না): "; read -s T; echo
  git clone "https://$U:$T@github.com/$U/$R.git" "$DIR"
  git -C "$DIR" config user.name "$U"
  git -C "$DIR" config user.email "$U@users.noreply.github.com"
fi

cd "$DIR"
git pull --rebase -q
python scrape.py bangla2
git add docs/bangla2.xml
git commit -q -m "Update bangla2 (Termux)" || echo "নতুন কিছু নেই"
git push -q
echo "== হয়ে গেছে: docs/bangla2.xml আপডেট হয়েছে =="
exit
}
