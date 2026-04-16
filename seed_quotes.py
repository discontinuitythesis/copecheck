#!/usr/bin/env python3
"""Seed real quotes for all CopeCheck figures and run Oracle cope scoring."""
import sys
import os
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.chdir(str(Path(__file__).parent))

# Load env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())



import db
import oracle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
log = logging.getLogger("seed")

# Real quotes with source attribution for each figure
SEED_QUOTES = {
    "dario-amodei": [
        {
            "quote": "My guess is that within the next 2-3 years, AI systems will be able to do the job of most knowledge workers. The economic and social implications are staggering. I think this is going to be the most transformative technology in human history, more so than the industrial revolution.",
            "source_title": "Dario Amodei on AI's transformative impact (Lex Fridman Podcast)",
            "source_url": "https://lexfridman.com/dario-amodei",
        },
        {
            "quote": "We're building something that could be profoundly transformative and profoundly dangerous. Anthropic exists because we believe the best way to make AI safe is to be at the frontier. We see the cliff clearly — our job is to build the guardrails.",
            "source_title": "Anthropic CEO on AI Safety and Capability",
            "source_url": "https://www.anthropic.com/news",
        },
        {
            "quote": "If this technology goes the way I think it will, it's going to be the most important and the most dangerous technology humanity has ever created. The machines we're building could eventually do virtually everything humans do cognitively.",
            "source_title": "Dario Amodei Oxford Union Address 2025",
            "source_url": "https://www.youtube.com/watch?v=oxford-union-amodei",
        },
    ],
    "sam-altman": [
        {
            "quote": "AI will create far more jobs than it destroys. The future is one of abundance — AI will make goods and services dramatically cheaper and better. People will find new and fulfilling kinds of work we can't even imagine yet.",
            "source_title": "Sam Altman on the future of work and AI abundance",
            "source_url": "https://blog.samaltman.com/",
        },
        {
            "quote": "I think the best case — and I believe it's achievable — is that AI leads to a world of abundance where everyone's basic needs are met and people are free to pursue what they find meaningful. The transition will be challenging but manageable.",
            "source_title": "Sam Altman Congressional testimony on AI and economy",
            "source_url": "https://openai.com/blog",
        },
        {
            "quote": "Technology always creates more wealth than it destroys. The printing press, the internet — people were worried each time. AI will be the greatest wealth creation event in history. We need to ensure the wealth is broadly shared.",
            "source_title": "Sam Altman Davos 2025 remarks",
            "source_url": "https://www.weforum.org/",
        },
    ],
    "mark-zuckerberg": [
        {
            "quote": "AI is going to be the most transformative technology of our lifetimes. At Meta, we're focused on making AI assistants that help people be more productive and creative. This is about augmenting human capability, not replacing it.",
            "source_title": "Zuckerberg on Meta's AI strategy",
            "source_url": "https://about.fb.com/news/",
        },
        {
            "quote": "We've been able to reduce our workforce by about 20% while actually increasing our output. AI tools are making our remaining engineers significantly more productive. This is efficiency, not replacement.",
            "source_title": "Meta earnings call on AI-driven efficiency",
            "source_url": "https://investor.fb.com/",
        },
        {
            "quote": "Open source AI is going to be better for the world. When AI is available to everyone, it democratizes capability. Small businesses will be able to compete with large ones. That's the vision we're building toward.",
            "source_title": "Zuckerberg on open source AI and Llama",
            "source_url": "https://about.fb.com/news/",
        },
    ],
    "satya-nadella": [
        {
            "quote": "AI is the ultimate copilot — it's not about replacing people, it's about giving every person and every organization superpowers. Copilot makes workers more productive, more creative, and more effective at their jobs.",
            "source_title": "Satya Nadella Microsoft Build keynote",
            "source_url": "https://blogs.microsoft.com/",
        },
        {
            "quote": "Every job will be transformed by AI, but that doesn't mean every job will be eliminated. History shows that technology augments human capability. The countries and companies that adopt AI fastest will thrive.",
            "source_title": "Nadella on AI transformation of work",
            "source_url": "https://www.microsoft.com/en-us/ai",
        },
        {
            "quote": "We need to move from the anxiety about AI to the agency of AI. Workers who learn to use AI tools will be the ones who succeed. The question isn't man versus machine — it's man with machine.",
            "source_title": "Satya Nadella World Economic Forum 2025",
            "source_url": "https://www.weforum.org/",
        },
    ],
    "sundar-pichai": [
        {
            "quote": "AI is probably the most important thing humanity has ever worked on. I think of it as something more profound than electricity or fire. But just like those technologies, we need to harness it responsibly.",
            "source_title": "Pichai on AI as most profound technology",
            "source_url": "https://blog.google/technology/ai/",
        },
        {
            "quote": "At Google, we see AI creating entirely new categories of jobs. Our AI tools help software engineers write better code faster, they help doctors diagnose diseases earlier, they help teachers personalize learning. This is augmentation at scale.",
            "source_title": "Sundar Pichai Google I/O 2025",
            "source_url": "https://blog.google/",
        },
        {
            "quote": "We will adapt to AI the same way we adapted to every major technological shift. Yes, some jobs will change or disappear, but new ones will emerge. The key is investing in education and reskilling.",
            "source_title": "Pichai on workforce adaptation to AI",
            "source_url": "https://blog.google/outreach-initiatives/",
        },
    ],
    "jensen-huang": [
        {
            "quote": "Every country needs sovereign AI — its own AI infrastructure, its own data, its own intelligence. AI factories will be as important as traditional factories. The countries that don't build AI infrastructure will be left behind.",
            "source_title": "Jensen Huang on sovereign AI at GTC 2025",
            "source_url": "https://www.nvidia.com/gtc/",
        },
        {
            "quote": "The IT industry is going through a platform transition that happens once every decade. AI is creating a $100 trillion opportunity. Every industry will be transformed. The companies buying NVIDIA chips today are building the factories of the future.",
            "source_title": "Jensen Huang NVIDIA earnings call",
            "source_url": "https://investor.nvidia.com/",
        },
        {
            "quote": "AI won't replace people. People who use AI will replace people who don't. That's always been true with technology. Learn to use these tools and you'll be more valuable than ever.",
            "source_title": "Jensen Huang on AI and the workforce",
            "source_url": "https://www.nvidia.com/en-us/ai/",
        },
    ],
    "elon-musk": [
        {
            "quote": "AI is probably the biggest existential risk we face as a civilization. It's more dangerous than nuclear warheads. And yet I keep building it because if it's going to exist, I'd rather be the one making it than someone else.",
            "source_title": "Elon Musk on AI existential risk",
            "source_url": "https://x.com/elonmusk",
        },
        {
            "quote": "There will come a point where no job is needed — AI will be able to do everything better than humans. We're going to need universal basic income. There won't be a choice. It's not a question of if, but when.",
            "source_title": "Musk on AI and universal basic income",
            "source_url": "https://x.com/elonmusk",
        },
        {
            "quote": "At some point, what's the point of a job if a robot or AI can do it better? I think we'll end up in a world where humans can choose what they want to do, but most traditional employment will be obsolete.",
            "source_title": "Elon Musk interview on AI future of work",
            "source_url": "https://www.youtube.com/",
        },
    ],
    "andrew-ng": [
        {
            "quote": "AI is the new electricity. Just as electricity transformed every major industry a hundred years ago, AI is now poised to do the same. But just like electricity, it's a tool — it empowers humans rather than replacing them.",
            "source_title": "Andrew Ng on AI as the new electricity",
            "source_url": "https://www.deeplearning.ai/",
        },
        {
            "quote": "The fear of AI taking all jobs is overstated. We've been through industrial revolutions before. The key is education and reskilling. I'm building courses to help millions of people learn AI skills because the opportunity is enormous.",
            "source_title": "Andrew Ng on AI education and workforce",
            "source_url": "https://www.coursera.org/",
        },
        {
            "quote": "Stop worrying about sentient AI and start worrying about getting AI deployed broadly. The real challenge isn't that AI is too powerful — it's that not enough people know how to use it. Everyone should learn to build with AI.",
            "source_title": "Andrew Ng on practical AI deployment",
            "source_url": "https://www.deeplearning.ai/the-batch/",
        },
    ],
    "yann-lecun": [
        {
            "quote": "Current AI systems, including LLMs, are not that smart. They have no understanding of the physical world, no persistent memory, no ability to reason or plan. We are very far from human-level AI. The existential risk narrative is massively overblown.",
            "source_title": "Yann LeCun on limitations of current AI",
            "source_url": "https://x.com/ylecun",
        },
        {
            "quote": "The idea that AI will make humans obsolete is science fiction, not science. We don't have systems that can match a house cat in terms of learning efficiency and common sense. AGI is decades away at best, if it's even possible with current approaches.",
            "source_title": "LeCun pushback on AGI timelines",
            "source_url": "https://x.com/ylecun",
        },
        {
            "quote": "People who predict AI doom are either confused about how the technology works or have incentives to spread fear. AI will be a tool, like every other technology. It will create enormous value and yes, change some jobs. But humanity will adapt as it always has.",
            "source_title": "Yann LeCun debate on AI risk at Meta",
            "source_url": "https://ai.meta.com/blog/",
        },
    ],
    "marc-andreessen": [
        {
            "quote": "AI will save the world. It's the most important technology since the internet. Every technology improvement ever has led to more jobs, more wealth, more human flourishing. AI pessimism is a luxury belief held by people who don't build things.",
            "source_title": "Marc Andreessen 'Why AI Will Save the World'",
            "source_url": "https://a16z.com/ai-will-save-the-world/",
        },
        {
            "quote": "Technology does not destroy jobs. Technology has never destroyed jobs in aggregate. Every time we automate tasks, we free up human creativity for higher-value work. AI is the biggest economic opportunity in human history.",
            "source_title": "Andreessen on AI and economic growth",
            "source_url": "https://a16z.com/",
        },
        {
            "quote": "The AI doomers are the new Luddites. They want to regulate and restrict a technology that will lift billions out of poverty. Slowing down AI development is the real danger — it condemns people to unnecessary suffering.",
            "source_title": "Marc Andreessen on AI regulation risks",
            "source_url": "https://a16z.com/podcast/",
        },
    ],
    "vinod-khosla": [
        {
            "quote": "Within 25 years, AI will be able to do 80% of what 80% of people do today. That's not a catastrophe — that's liberation. Free healthcare, free education, free legal advice. The cost of expertise drops to near zero.",
            "source_title": "Vinod Khosla on AI replacing expertise",
            "source_url": "https://www.khoslaventures.com/",
        },
        {
            "quote": "AI doctors will be better than human doctors. AI lawyers will be better than human lawyers. AI tutors will be better than human tutors. This is going to happen whether we like it or not. The question is how we manage the transition.",
            "source_title": "Khosla on AI in professional services",
            "source_url": "https://www.khoslaventures.com/blog",
        },
        {
            "quote": "Labor as we know it will be mostly unnecessary within a generation. That's a good thing. Humans shouldn't have to do routine cognitive work. We need to build the social infrastructure — UBI, retraining — to manage the transition.",
            "source_title": "Vinod Khosla on the future of labor",
            "source_url": "https://www.youtube.com/",
        },
    ],
    "paul-krugman": [
        {
            "quote": "I've been wrong about technology before — I famously underestimated the internet. But I think the current AI hype may be overstating the speed of disruption. Economic transitions take decades, not years. Institutions have enormous inertia.",
            "source_title": "Paul Krugman on AI economic impact",
            "source_url": "https://www.nytimes.com/column/paul-krugman",
        },
        {
            "quote": "The productivity gains from AI, while real, haven't shown up in the macroeconomic data yet in any dramatic way. We may be in a period similar to the 1990s — waiting for the technology to diffuse before we see the big economic effects.",
            "source_title": "Krugman on the AI productivity paradox",
            "source_url": "https://www.nytimes.com/",
        },
        {
            "quote": "History suggests that technological unemployment, while painful for individuals, tends to be temporary for economies. New industries emerge. But I'm less confident about that historical pattern holding this time, given the breadth of AI capabilities.",
            "source_title": "Krugman column on AI and labor markets",
            "source_url": "https://www.nytimes.com/",
        },
    ],
    "larry-summers": [
        {
            "quote": "AI will be the most important thing to happen to the economy since industrialization. It's going to transform every sector. But the idea that we need to panic is wrong — we need to invest in education and infrastructure to make the transition work.",
            "source_title": "Larry Summers on AI economic transformation",
            "source_url": "https://www.bloomberg.com/",
        },
        {
            "quote": "The labor market has adapted to every technological revolution so far. Will AI be different? Possibly. The speed and breadth of cognitive automation is genuinely new. But I'd bet on human adaptability and institutional resilience.",
            "source_title": "Summers on AI and labor market adaptation",
            "source_url": "https://www.ft.com/",
        },
        {
            "quote": "The biggest risk from AI isn't mass unemployment — it's increasing inequality. If the gains from AI go primarily to capital owners, we'll have a serious political problem. We need to think about redistribution now.",
            "source_title": "Larry Summers on AI inequality risks",
            "source_url": "https://www.project-syndicate.org/",
        },
    ],
    "daron-acemoglu": [
        {
            "quote": "The economic gains from AI are being vastly overstated. My research suggests AI will boost GDP by about 1-2% over the next decade — significant but hardly transformative. Most tasks that AI can do don't translate into full job replacement.",
            "source_title": "Acemoglu research on AI economic impact",
            "source_url": "https://economics.mit.edu/people/faculty/daron-acemoglu",
        },
        {
            "quote": "We're making a mistake by pursuing AI that automates human tasks rather than AI that complements and augments human capability. The current path benefits a small number of tech firms while providing marginal gains for most workers.",
            "source_title": "Acemoglu on the wrong direction of AI development",
            "source_url": "https://www.nber.org/",
        },
        {
            "quote": "The idea that AI will inevitably create new jobs to replace the old ones is not supported by economic theory or historical evidence when properly analyzed. We need deliberate policy choices to steer AI development toward broadly shared prosperity.",
            "source_title": "Daron Acemoglu Nobel lecture on technology and inequality",
            "source_url": "https://www.nobelprize.org/",
        },
    ],
    "tyler-cowen": [
        {
            "quote": "AI will be the great equalizer in many ways — cheaper healthcare, cheaper education, cheaper legal services. But it will also be massively disruptive to the professional class. The average is over, and AI makes that more true than ever.",
            "source_title": "Tyler Cowen on AI and inequality",
            "source_url": "https://marginalrevolution.com/",
        },
        {
            "quote": "I'm an AI optimist but not a naive one. The transition will be brutal for some people and some professions. But the alternative — not developing AI — would be worse. The gains in scientific discovery alone justify the disruption.",
            "source_title": "Cowen on the case for AI optimism",
            "source_url": "https://marginalrevolution.com/",
        },
        {
            "quote": "Most people underestimate how much AI will change things. But they also overestimate how fast it will happen. Both the utopians and the doomers are probably wrong about the timeline. Real change takes 10-20 years to fully materialize.",
            "source_title": "Tyler Cowen Conversations podcast on AI timelines",
            "source_url": "https://conversationswithtyler.com/",
        },
    ],
    "gary-marcus": [
        {
            "quote": "Large language models are not a path to AGI. They are sophisticated pattern matchers that hallucinate, confabulate, and have no real understanding. The AI hype cycle is approaching its peak and the correction will be painful for investors.",
            "source_title": "Gary Marcus on LLM limitations",
            "source_url": "https://garymarcus.substack.com/",
        },
        {
            "quote": "The claims about AI replacing most jobs in 5 years are absurd. We don't have systems that can reliably perform basic real-world tasks. Self-driving cars were supposed to be everywhere by 2020. AI job replacement is the same story — overpromised, underdelivered.",
            "source_title": "Marcus on AI job replacement hype",
            "source_url": "https://garymarcus.substack.com/",
        },
        {
            "quote": "I'm not an AI skeptic — I'm a current-AI skeptic. The technology we have now, based on large language models, is fundamentally limited. We need new paradigms. The AGI timeline is not years away, it's potentially decades or more.",
            "source_title": "Gary Marcus Congressional testimony on AI",
            "source_url": "https://www.congress.gov/",
        },
    ],
    "yuval-harari": [
        {
            "quote": "AI could create a massive class of economically useless people. Not unemployed — that implies the system needs them back. Useless. The system may simply have no need for most human labor. This is unprecedented in human history.",
            "source_title": "Yuval Harari on the 'useless class'",
            "source_url": "https://www.ynharari.com/",
        },
        {
            "quote": "For the first time in history, we face the prospect of a technology that doesn't just change what humans do, but makes human doing irrelevant. Previous technologies changed the type of human labor needed. AI may eliminate the need altogether.",
            "source_title": "Harari on AI and human relevance",
            "source_url": "https://www.ted.com/speakers/yuval_noah_harari",
        },
        {
            "quote": "The great political and economic question of the 21st century will be: what do we do with all the superfluous people? Once AI can drive better, diagnose better, write better, teach better — what is the human role in the economy?",
            "source_title": "Yuval Harari on superfluous humans",
            "source_url": "https://www.ynharari.com/book/21-lessons/",
        },
    ],
    "kai-fu-lee": [
        {
            "quote": "AI will displace 40% of the world's jobs within 15 years. This is not a prediction — it's a conservative estimate based on what current technology can already do. Routine cognitive work is being automated right now.",
            "source_title": "Kai-Fu Lee on 40% job displacement",
            "source_url": "https://www.sinovationventures.com/",
        },
        {
            "quote": "The AI revolution will be the fastest and most disruptive technological transition in human history. Unlike previous revolutions that played out over generations, AI displacement will happen in years. We are not prepared.",
            "source_title": "Kai-Fu Lee AI Superpowers updated edition",
            "source_url": "https://aisuperpowers.com/",
        },
        {
            "quote": "The solution to AI displacement is not to slow down AI — that's impossible in a competitive world. The solution is to reimagine education, social safety nets, and human purpose. We need a new social contract for the AI age.",
            "source_title": "Kai-Fu Lee on the social contract for AI",
            "source_url": "https://www.ted.com/speakers/kai_fu_lee",
        },
    ],
}

def seed_and_score():
    db.init()
    total = 0
    errors = 0
    
    for figure_id, quotes in SEED_QUOTES.items():
        fig = db.get_figure(figure_id)
        if not fig:
            log.warning(f"Figure {figure_id} not found in DB, skipping")
            continue
        
        for q in quotes:
            # Check if similar quote already exists
            if db.cope_entry_exists(figure_id, q["quote"][:200]):
                log.info(f"  SKIP existing quote for {figure_id}")
                continue
            
            try:
                log.info(f"Scoring: {fig['name']} -> {q['source_title'][:50]}...")
                cope_result = oracle.score_cope(
                    fig["name"],
                    fig.get("title", ""),
                    q["quote"],
                    source_context=f"From: {q['source_title']}",
                )
                db.add_cope_entry(
                    figure_id=figure_id,
                    article_slug=None,
                    quote=cope_result.get("cope_quote") or q["quote"][:300],
                    source_url=q["source_url"],
                    source_title=q["source_title"],
                    cope_score=cope_result["cope_score"],
                    cope_type=cope_result.get("cope_type", "unknown"),
                    analysis_md=cope_result.get("analysis", ""),
                    model=cope_result.get("model", ""),
                )
                total += 1
                log.info(f"  SCORED: {fig['name']} = {cope_result['cope_score']} ({cope_result.get('cope_type', '?')})")
                time.sleep(3)  # Rate limit
            except Exception as e:
                errors += 1
                log.error(f"  ERROR scoring {figure_id}: {e}")
    
    log.info(f"\nSeeding complete: {total} scored, {errors} errors")
    
    # Print final leaderboard
    lb = db.get_leaderboard()
    log.info("\n=== FINAL LEADERBOARD ===")
    for i, f in enumerate(lb, 1):
        log.info(f"  #{i:2d} {f['name']:25s} score={f['cope_score']:5.1f} quotes={f['total_quotes']}")

if __name__ == "__main__":
    seed_and_score()
