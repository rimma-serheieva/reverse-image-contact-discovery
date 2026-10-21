"""
verify.py — is this email address actually deliverable? No paid API: an MX
lookup plus a raw SMTP handshake, stopped before actually sending anything.

HOW IT WORKS
    1. Look up the domain's MX record — if there's no mail server, nothing
       else matters.
    2. Open an SMTP connection to that server and run HELO / MAIL FROM /
       RCPT TO, then QUIT without sending DATA. A well-behaved mail server
       answers RCPT TO honestly: 250 means "I'd accept mail for this
       address," 550-series means "no such mailbox."

HONEST LIMITATION
    Plenty of real mail servers (Gmail among them) don't answer this
    question truthfully — they accept-all at the SMTP layer and reject
    later, or they rate-limit/block probing connections outright. So this
    returns one of four verdicts, and "unknown" is reported as unknown
    rather than guessed at:
        deliverable      the server explicitly accepted the address
        rejected         the server explicitly refused it — do not send
        catch_all        the domain accepts anything; can't be confirmed
        unknown          no answer, blocked, or timed out
"""
import smtplib
import socket

import dns.resolver


def mx_hosts(domain, timeout=8):
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=timeout)
        return sorted((r.preference, str(r.exchange).rstrip(".")) for r in answers)
    except Exception:
        return []


def check(email, from_addr="verify-probe@example.com", timeout=10):
    if "@" not in email:
        return "unknown", "not an email"
    domain = email.split("@", 1)[1]
    hosts = mx_hosts(domain)
    if not hosts:
        return "unknown", "no MX record for %s" % domain

    host = hosts[0][1]
    try:
        smtp = smtplib.SMTP(timeout=timeout)
        smtp.connect(host, 25)
        smtp.helo("verify-probe.local")
        smtp.mail(from_addr)
        code_real, _ = smtp.rcpt(email)
        # a catch-all domain accepts everything, including a clearly bogus
        # address at the same domain — ask it that too, for comparison
        code_bogus, _ = smtp.rcpt("definitely-not-a-real-mailbox-xyz123@" + domain)
        smtp.quit()
        if code_real in (250, 251):
            if code_bogus in (250, 251):
                return "catch_all", "domain accepts any address at %s" % host
            return "deliverable", "accepted by %s" % host
        if 500 <= code_real < 600:
            return "rejected", "refused by %s (code %d)" % (host, code_real)
        return "unknown", "ambiguous response %d from %s" % (code_real, host)
    except (socket.timeout, smtplib.SMTPException, OSError) as e:
        return "unknown", "%s (%s blocks or rate-limits probes, as many do)" % (
            type(e).__name__, host)
