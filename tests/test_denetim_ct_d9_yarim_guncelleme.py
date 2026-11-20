"""R4-1: guncelleme betigi motor durdurulduktan sonra oldurulurse (systemd TimeoutStartSec=20min / OOM / SIGKILL) motor DURUK kalir; sonraki saatlik calisma motoru hic baslatmaz."""
import subprocess

from tests.test_deploy_sanal import GUNCELLE, YESIL, sunucu  # noqa: F401


def test_oldurulen_guncelleme_sonrasi_motor_yeniden_baslar(sunucu, tmp_path):  # noqa: F811
    bin_ = tmp_path / "bin"
    state = tmp_path / "state"
    state.mkdir()
    # durum izleyen sahte systemctl
    (bin_ / "systemctl").write_text(
        '#!/usr/bin/env bash\necho "systemctl $*" >> "$CAGRI_LOG"\n'
        'case "$1" in\n'
        ' is-active) [ ! -f "$STATE/$3.durdu" ] && [ ! -f "$STATE/$2.durdu" ]; exit $?;;\n'
        ' stop) for u in "${@:2}"; do touch "$STATE/$u.durdu"; done; exit 0;;\n'
        ' start) for u in "${@:2}"; do rm -f "$STATE/$u.durdu"; [ "$u" = sg-sanal ] && printf \'{"yazildi_ms": %s}\' "$(( $(date +%s) * 1000 ))" > "$SANAL_DEPO/durum/ozet.json"; done; exit 0;;\n'
        ' show) case "$*" in *Result*) echo success;; *) echo 0;; esac; exit 0;;\n'
        'esac\nexit 0\n')
    (bin_ / "systemctl").chmod(0o755)
    venv = tmp_path / "serit/venv/bin"
    venv.mkdir(parents=True)
    pip = venv / "pip"
    pip.write_text('#!/usr/bin/env bash\nif [ -n "${PIP_OLDUR:-}" ]; then kill -KILL $PPID; sleep 5; fi\nexit 0\n')
    pip.chmod(0o755)
    sunucu.ortak["STATE"] = str(state)
    sunucu.yeni_commit("v2", lock="a==2\n")
    sunucu.ci(*YESIL)
    r = subprocess.run(["bash", str(GUNCELLE)], env={**sunucu.ortak, "PIP_OLDUR": "1"}, capture_output=True, text=True)
    assert (state / "sg-sanal.durdu").exists(), "motor durdurulmus olmali (olduruldu)"
    # saatlik timer ikinci kez calisir
    r = subprocess.run(["bash", str(GUNCELLE)], env=sunucu.ortak, capture_output=True, text=True)
    print(r.stdout)
    assert not (state / "sg-sanal.durdu").exists(), "BEKLENEN: motor yeniden baslatilmis; GERCEK: durmus kaliyor\n" + r.stdout


def _kurulum(sunucu, tmp_path):  # noqa: F811
    """Ortak: durum izleyen sahte systemctl + öldürülebilir pip; ilk (öldürülen) çalışmadan sonraki sunucuyu döner."""
    bin_ = tmp_path / "bin"
    state = tmp_path / "state"
    state.mkdir()
    (bin_ / "systemctl").write_text(
        '#!/usr/bin/env bash\necho "systemctl $*" >> "$CAGRI_LOG"\n'
        'case "$1" in\n'
        ' is-active) [ ! -f "$STATE/$3.durdu" ] && [ ! -f "$STATE/$2.durdu" ]; exit $?;;\n'
        ' stop) for u in "${@:2}"; do touch "$STATE/$u.durdu"; done; exit 0;;\n'
        ' start) for u in "${@:2}"; do rm -f "$STATE/$u.durdu"; [ "$u" = sg-sanal ] && printf \'{"yazildi_ms": %s}\' "$(( $(date +%s) * 1000 ))" > "$SANAL_DEPO/durum/ozet.json"; done; exit 0;;\n'
        ' show) case "$*" in *Result*) echo success;; *) echo 0;; esac; exit 0;;\n'
        'esac\nexit 0\n')
    venv = tmp_path / "serit/venv/bin"
    venv.mkdir(parents=True)
    pip = venv / "pip"
    pip.write_text('#!/usr/bin/env bash\nif [ -n "${PIP_OLDUR:-}" ]; then kill -KILL $PPID; sleep 5; fi\nexit 0\n')
    pip.chmod(0o755)
    sunucu.ortak["STATE"] = str(state)
    yeni = sunucu.yeni_commit("v2", lock="a==2\n")
    sunucu.ci(*YESIL)
    subprocess.run(["bash", str(GUNCELLE)], env={**sunucu.ortak, "PIP_OLDUR": "1"}, capture_output=True, text=True)
    return state, yeni


def test_yarim_guncelleme_tamamlanir_tek_uyari_ve_sha_yazilir(sunucu, tmp_path):  # noqa: F811
    state, yeni = _kurulum(sunucu, tmp_path)
    assert (sunucu.durum / "yarim").exists() and sunucu.head() == yeni
    sunucu.log.write_text("")
    r = subprocess.run(["bash", str(GUNCELLE)], env=sunucu.ortak, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    assert not (state / "sg-sanal.durdu").exists()
    assert (sunucu.durum / "uygulanan_sha").read_text().strip() == yeni and not (sunucu.durum / "yarim").exists()
    mesajlar = [x for x in sunucu.log.read_text().splitlines() if x.startswith("TG:")]
    assert len(mesajlar) == 1 and "Yarım kalan güncelleme tamamlandı, bot yeniden başlatıldı" in mesajlar[0]
    sunucu.log.write_text("")
    subprocess.run(["bash", str(GUNCELLE)], env=sunucu.ortak, capture_output=True, text=True)     # üçüncü çalışma: sessiz
    assert "TG:" not in sunucu.log.read_text() and "systemctl stop" not in sunucu.log.read_text()


def test_yarim_guncelleme_kasitli_dur_varsa_motor_baslatilmaz(sunucu, tmp_path):  # noqa: F811
    state, _ = _kurulum(sunucu, tmp_path)
    (sunucu.depo / "durum/DUR").write_text("elle\n")
    subprocess.run(["bash", str(GUNCELLE)], env=sunucu.ortak, capture_output=True, text=True)
    assert (state / "sg-sanal.durdu").exists()


def test_yarim_guncelleme_dondurulmussa_motor_baslatilmaz(sunucu, tmp_path):  # noqa: F811
    state, yeni = _kurulum(sunucu, tmp_path)
    (sunucu.durum / "dondur").write_text(yeni + "\n")
    subprocess.run(["bash", str(GUNCELLE)], env=sunucu.ortak, capture_output=True, text=True)
    assert (state / "sg-sanal.durdu").exists()


def test_kasitli_elle_durdurma_isaretsiz_ezilmez(sunucu, tmp_path):  # noqa: F811
    """Güncelleme hiç yarıda kalmadıysa (işaret yok) elle durdurulan motor güncelleme betiğince başlatılmaz."""
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "bin/systemctl").write_text('#!/usr/bin/env bash\necho "systemctl $*" >> "$CAGRI_LOG"\ncase "$1" in is-active) exit 3;; show) echo 0;; esac\nexit 0\n')
    sunucu.ortak["STATE"] = str(state)
    r = subprocess.run(["bash", str(GUNCELLE)], env=sunucu.ortak, capture_output=True, text=True)
    assert r.returncode == 0 and "systemctl start" not in sunucu.log.read_text()
