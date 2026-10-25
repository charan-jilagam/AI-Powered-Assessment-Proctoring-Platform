import { Fragment } from 'react'
import { Link, Navigate, useParams } from 'react-router-dom'
import { ArrowLeft, BookOpen, ClipboardCheck, GraduationCap, Landmark, ShieldCheck } from 'lucide-react'
import { ThemeToggle } from '../../lib/theme'
import { useDocumentTitle } from '../../lib/hooks'

// **bold** and `code` inside plain strings keep the content below easy to edit.
function Rich({ text }) {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith('**')) return <b key={i}>{part.slice(2, -2)}</b>
    if (part.startsWith('`')) return <code key={i}>{part.slice(1, -1)}</code>
    return <Fragment key={i}>{part}</Fragment>
  })
}

const GUIDES = {
  candidate: {
    label: 'Candidates', icon: GraduationCap, who: 'You are taking a test',
    intro: 'Taking a test takes about two minutes to set up. You do not need an account or a password, only the 8-character code or link your organizer sent you and access to your e-mail inbox.',
    sections: [
      { title: 'Before the day', items: [
        'Use a laptop or desktop with the latest **Chrome, Edge or Firefox**. Phones and tablets are not supported for proctored tests.',
        'Check your **camera** (and microphone, if the test says so) works and that your face is well lit. Close other apps and browser tabs.',
        'Use an **e-mail address you can open right now**. We send a 6-digit code to it before you can start.',
        'Find a quiet, well-lit place. If your organizer asks for ID, keep it next to you.',
      ] },
      { title: 'Joining a test', steps: [
        'Open the link from your organizer, or go to the ORVEXA home page and type the 8-character **test code** under “Taking a test?”.',
        'Enter your **full name** (as on your ID) and **e-mail**, plus anything else the organizer asks for. Some tests also need an **access password**, which the organizer gives you separately.',
        'Press **Send verification code**. Open the e-mail, copy the **6-digit code** and enter it. The code works for 10 minutes and for one test only. Did not arrive? Check spam, then press **Resend** after the short wait.',
        'Some organizations only accept addresses from their own domain (for example `@company.com`). The page tells you if that is the case.',
        'Tick the agreement and continue to the waiting room.',
      ] },
      { title: 'The waiting room', steps: [
        'Allow the **camera** (and microphone) when your browser asks. You will see yourself in the preview.',
        'If the test needs identity verification, take a **face photo** and hold your **ID** to the camera for a second photo.',
        'Read the organizer’s instructions, accept the proctoring terms, then press **Start the test**. The clock starts now and cannot be paused.',
        'Tests that need it run in **fullscreen**. Your browser will ask for permission.',
      ] },
      { title: 'During the test', items: [
        'The **question list** on the side shows what you answered. Use **Flag for review** to come back to a question later. Answers save automatically.',
        'The **timer** is kept by the server. If your computer sleeps, the time still passes. When it reaches zero your answers are submitted for you.',
        'Do not switch tabs, leave fullscreen, copy and paste, or open developer tools. These are **recorded**. Small notices fade away; **serious warnings** count towards a limit and, if you reach it, the test ends.',
        'Keep your face in view. Looking away briefly is fine; leaving the frame, covering the camera or having another person in view is flagged.',
        'If your internet drops, reopen the same link, enter the **same e-mail** and a **new code**, and you continue where you left off.',
      ] },
      { title: 'Coding questions', steps: [
        'Pick a **language** from the list above the editor. Starter code appears for each language. Java programs must use the class name `Main`.',
        'Read the input and output format. Your program reads from **standard input** and prints to **standard output**.',
        'Press **Run** to try the visible sample cases, or tick **Run with my own input** to test any input. Running does not count towards your score.',
        'Press **Submit** to be graded against **all** tests, including hidden ones. You can submit as often as you like; your **best** result counts. Wait a few seconds between runs.',
      ] },
      { title: 'Finishing', items: [
        'Press **Submit test** when you are done. You will be asked to confirm.',
        'Depending on the organizer’s settings you see your score straight away, a detailed review, or just a confirmation.',
        'Close the tab afterwards. Nothing is kept on your computer.',
      ] },
      { title: 'If something goes wrong', items: [
        '**Code not found:** check the 8 characters. Letters O/I/L and digits 0/1 are never used, so they cannot be mistyped.',
        '**Camera blocked:** click the camera icon in the address bar, allow access, then reload the page and join again with the same e-mail.',
        '**Test closed or not open yet:** contact the organizer. The page shows the opening and closing times.',
        '**“You have already completed this test”:** only the organizer can allow a retake.',
      ] },
    ],
  },
  admin: {
    label: 'Admins & test creators', icon: ClipboardCheck, who: 'You create and manage tests for your organization',
    intro: 'Admins build tests, share codes, watch live sessions and review results. Your organization is created by the ORVEXA platform owner, who also sends your first invitation.',
    sections: [
      { title: 'First sign-in: activate and verify', steps: [
        'Open the **invitation e-mail** and press **Set your password**. Choose a password with at least 10 characters including a letter and a number, then sign in.',
        'You will also receive a second e-mail, **“Verify your e-mail address”**. Press its button. **You cannot create tests until this is done**; a yellow banner reminds you and lets you resend the link.',
        'Link expired or lost? Use **Resend verification e-mail** in the banner. Still stuck? Ask the platform owner to verify you manually.',
        'Your organization may only allow addresses from its own e-mail domains (for example `@yourcompany.com`). This applies to you and to every team member you add.',
      ] },
      { title: 'Try the two trial tests', items: [
        'Every new organization starts with **two ready-made trial tests**: “[Trial] General Aptitude & Tech Basics” (10 questions, all question types) and “[Trial] Coding Challenge” (3 questions and 2 coding problems).',
        'Open **Tests**, copy a trial test’s code, and take it yourself in another browser window to see exactly what candidates see. Then open **Results** to see scoring and the proctoring report.',
        'Trial tests are labelled **Trial**, are already published, and do not count against your plan’s active-test limit. Edit or delete them freely. Missing? Press **Add the 2 trial tests** on the Tests page.',
      ] },
      { title: 'Create a test', steps: [
        'Go to **Tests → New test**. Enter a title, duration and passing score. A unique 8-character **test code** is created for you.',
        'Open the **Questions** tab and add questions (see below). Open **Settings** to schedule the test, choose how candidates join, and set proctoring.',
        'Press **Publish**. Candidates can now join with the code or the share link. **Close** stops new joiners; people already inside can finish. **Unpublish** returns it to draft while nobody has started.',
        'Lost control of a code? **New code** replaces it immediately.',
      ] },
      { title: 'Adding questions', items: [
        '**By hand:** single choice, multiple choice, true/false and short answer, with marks, negative marks, sections, difficulty and an explanation shown in the review.',
        '**From the question bank:** reuse questions you saved earlier, or the built-in starter library (Python, JavaScript, SQL, data structures, CS fundamentals, aptitude).',
        '**CSV import:** download the template on the Questions tab, fill it in, upload. It is all-or-nothing and tells you which rows to fix.',
        '**Questions per candidate** draws a random subset; **shuffle** mixes questions and options so neighbours see different orders.',
      ] },
      { title: 'Coding problems: by hand or from JSON', steps: [
        'Open the test’s **Coding** tab. Press **Add problem** to type one in: title, statement, input/output format, points, time and memory limits, and test cases.',
        'Mark some test cases as **Sample** (candidates see them and can Run them). Leave the rest **hidden**: candidates only learn pass or fail.',
        'To add many problems at once, press **Import JSON**. Paste JSON or upload a `.json` file, press **Check JSON** to validate without saving, then **Import**. It is all-or-nothing: any mistake is listed by problem number and nothing is saved.',
        'Press **JSON format** at any time to see every field, an example you can copy or download, and the limits (50 problems per import, 50 test cases per problem).',
        'Candidates can write their solution in many languages (Python, C, C++, Java, JavaScript, TypeScript, C#, Go, Rust, Ruby, PHP and more). The list shown to them depends on what your platform’s code runner supports.',
      ] },
      { title: 'Who can join', items: [
        '**Code mode (default):** anyone with the code. Add an **access password** for a second factor you share separately.',
        '**Invite-only:** only e-mail addresses you invite. Use the **Invites** tab to paste or upload a list; each person gets a personal link.',
        '**E-mail verification is always on for candidates.** Before joining, each candidate must enter a 6-digit code sent to their address, so the e-mail on every result is real.',
        '**Domain lock:** if the platform owner registered your company domains, you can switch on “Only allow our e-mail domains” in **Integrations → Branding** so only people at those domains can join.',
        'Set an **opening and closing time**, a **maximum number of attempts**, and **custom fields** (roll number, department…) to collect from candidates.',
      ] },
      { title: 'Proctoring', items: [
        'Choose what is required: webcam, microphone, fullscreen, ID photo, AI face checks, tab-switch detection, copy/paste and right-click blocking.',
        'Decide whether **serious violations end the test automatically** and after how many. AI findings are for human review unless you allow them to terminate.',
        'AI monitoring needs a plan that includes it; the setting is switched off with a notice if it does not.',
      ] },
      { title: 'During and after the test', steps: [
        'Open the **Live** tab to see who is online, their warnings and risk. You can **message** a candidate, **add time**, or **end** an attempt.',
        'Open **Results** for scores, ranking and CSV export. Click a candidate for the full report: answers, integrity timeline, snapshots, code submissions and similarity to other candidates.',
        '**Review queue** lists attempts that need a decision. Confirm or dismiss each violation, then mark the attempt **cleared**, **suspicious** or **disqualified** with a note.',
        'Print the **PDF report** for any attempt. To let someone retake, **void** their attempt.',
      ] },
      { title: 'Your organization', items: [
        '**Team:** add admins and reviewers (they get an invitation and a verification e-mail). Reviewers can monitor and review but cannot change tests, team or billing.',
        '**Integrations:** logo and colour for candidate pages, API keys, and signed webhooks to send results to your own systems (when your plan includes them).',
        '**Plan & usage:** see limits and upgrade online. **Audit log** records who did what.',
      ] },
    ],
  },
  reviewer: {
    label: 'Reviewers', icon: ShieldCheck, who: 'You monitor sessions and review results',
    intro: 'Reviewers see everything needed to decide whether a result can be trusted, without being able to change tests, the team or billing.',
    sections: [
      { title: 'Getting started', steps: [
        'Accept the **invitation e-mail** and set your password, then sign in. Verify your e-mail from the second message when asked.',
        'You land on the dashboard: tests, attempts in progress, and attempts waiting for review.',
      ] },
      { title: 'Watching a live test', items: [
        'Open **Tests → the test → Live**. Each candidate shows status, warnings and risk score, and updates every few seconds.',
        'Send a **message** that appears on the candidate’s screen, or **extend time** after a technical problem. Admins can end an attempt; ask one if you need it.',
      ] },
      { title: 'Reviewing an attempt', steps: [
        'Open **Review queue**. Attempts with enough risk, or flagged by AI, are listed first.',
        'Open one. You see the **integrity timeline** (tab switches, fullscreen exits, camera loss, AI findings) with snapshot evidence, their answers, and code submissions with a similarity score against other candidates.',
        '**Confirm** a violation that is real, **dismiss** a false alarm (a face partly out of frame, a cough). Add a note explaining your reasoning.',
        'Choose a decision: **cleared**, **suspicious** or **disqualified**. The decision and your name appear on the printable PDF report.',
      ] },
      { title: 'Good practice', items: [
        'Treat AI findings and risk scores as **evidence, not proof**. Look at the snapshots before deciding.',
        'Similarity between code submissions is a screening aid. Common solutions to easy problems often look alike.',
        'Reviewers never see answer keys or hidden test cases.',
      ] },
    ],
  },
  owner: {
    label: 'Platform owner', icon: Landmark, who: 'You run the ORVEXA platform',
    intro: 'The platform owner (super admin) onboards client organizations, assigns plans, and keeps the platform healthy.',
    sections: [
      { title: 'First-time setup', items: [
        'Set `SUPERADMIN_EMAIL` and `SUPERADMIN_PASSWORD` on the server; the first start creates your account. Sign in at `/signin` and change the password under **Account**.',
        'Configure **e-mail delivery** (`BREVO_API_KEY`, `RESEND_API_KEY` or `SMTP_HOST`, plus `MAIL_FROM`). Without it nobody receives verification links, invitations or candidate codes, and the Overview page shows a red warning.',
        'Set `FRONTEND_URL` to your public address, and connect MongoDB, Cloudinary and Razorpay as described in the deployment guide.',
      ] },
      { title: 'Creating an organization', steps: [
        'Open **Organizations → New organization**. Choose the **plan** and whether it **starts as a trial** or paid.',
        'Enter the **first admin’s** name and e-mail. Use a work address that matches the organization’s domain.',
        'Under **Allowed e-mail domains** list the organization’s domains, for example `sconexsoft.com`. Team members must then use those domains, and you can also lock candidates to them. Leave it empty to allow any address.',
        'Keep **Add the 2 trial tests** ticked so the admin has something to try immediately.',
        'The admin receives an **invitation** (set password) and a **verification** e-mail. They cannot create tests until verified. You can copy the activation link to send it yourself, or set a temporary password.',
      ] },
      { title: 'Managing organizations', items: [
        'Open an organization to see usage against limits, its staff, and recent activity. **Override limits** for custom deals; **Suspend** or **Cancel** to block access immediately.',
        'Edit **allowed e-mail domains** and the **candidate domain lock** at any time from the organization page.',
        'In the Staff table, **Verify e-mail** marks a person as verified when you have confirmed them another way, and **Send verification** re-sends the link.',
        '**Reset link** issues a one-time password-reset link; **Disable** blocks a user.',
      ] },
      { title: 'Platform tools', items: [
        '**Plans:** prices, seats, active tests, candidates per month and features such as AI proctoring, coding, API and webhooks.',
        '**Demo requests:** leads from the landing page. **E-mail outbox:** every message the platform sent or tried to send, with errors.',
        '**Platform admins** and the **audit log** cover your own team and every sensitive action.',
        '**Code runner:** coding questions run on Judge0 when `JUDGE0_URL` is set, otherwise on the built-in runner inside the server. See the deployment guide for the trade-offs.',
      ] },
    ],
  },
}

const ORDER = ['candidate', 'admin', 'reviewer', 'owner']

export default function Guide() {
  const { role } = useParams()
  const g = GUIDES[role]
  useDocumentTitle(g ? `${g.label} guide` : 'User guides')
  if (role && !g) return <Navigate to="/guide" replace />
  return (
    <div className="landing guide">
      <header className="l-nav">
        <Link to="/" className="brand"><img src="/brand/orvexa-emblem.png" alt="" width="34" height="34" />ORVEXA</Link>
        <nav><Link to="/">Home</Link><Link to="/guide">User guides</Link><ThemeToggle /><Link className="btn sm" to="/signin">Sign in</Link></nav>
      </header>
      {!g ? (
        <section className="l-section">
          <h1 className="guide-h1">User guides</h1>
          <p className="muted-2" style={{ maxWidth: '40em' }}>Pick the guide that matches what you do. Each one walks through the screens in the order you will meet them.</p>
          <div className="guide-cards">
            {ORDER.map((k) => { const x = GUIDES[k]; return (
              <Link key={k} to={`/guide/${k}`} className="guide-card"><x.icon size={22} /><h2>{x.label}</h2><p>{x.who}</p><span>Open guide →</span></Link>) })}
          </div>
        </section>
      ) : (
        <section className="l-section guide-body">
          <aside className="guide-toc" aria-label="Guide navigation">
            <Link to="/guide" className="back"><ArrowLeft size={14} />All guides</Link>
            <div className="roles">{ORDER.map((k) => <Link key={k} to={`/guide/${k}`} className={k === role ? 'active' : ''}>{GUIDES[k].label}</Link>)}</div>
            <div className="toc">{g.sections.map((s, i) => <a key={s.title} href={`#s${i}`}>{s.title}</a>)}</div>
          </aside>
          <article>
            <div className="guide-hero"><g.icon size={26} /><div><h1 className="guide-h1">{g.label}</h1><p className="muted-2">{g.who}</p></div></div>
            <p className="guide-intro"><Rich text={g.intro} /></p>
            {g.sections.map((s, i) => (
              <section key={s.title} id={`s${i}`} className="guide-sec">
                <h2>{s.title}</h2>
                {s.steps && <ol>{s.steps.map((t, n) => <li key={n}><Rich text={t} /></li>)}</ol>}
                {s.items && <ul>{s.items.map((t, n) => <li key={n}><Rich text={t} /></li>)}</ul>}
              </section>
            ))}
            <p className="muted-2 guide-end"><BookOpen size={14} /> Need more help? Contact your organizer, or the person who set up ORVEXA for your company.</p>
          </article>
        </section>
      )}
    </div>
  )
}
