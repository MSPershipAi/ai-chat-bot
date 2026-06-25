from groq import Groq # type: ignore
import json

def route_query(user_query: str) -> dict:
    """
    Routes a user query to the appropriate agent using Groq's LLM.
    
    Args:
        user_query (str): Input question from the user.
    
    Returns:
        dict: JSON response with selected_agent, reason, and optional answer.
    """
    client = Groq()  # Ensure GROQ_API_KEY is in your environment variables
    
    system_prompt = """
    You are a Manager Agent at Equilibrium.ai for Pership Group. 
    Your task is to analyze user queries and route them to EXACTLY ONE of these agents:
    1. RAG_Agent: For questions about internal documents, policies, and standard operating procedures.
    
    Respond STRICTLY in JSON format like this:
    {
      "selected_agent": "Agent_Name", 
      "reason": "Brief explanation to use this agent"
      "answer": "Using <Agent_Name> for this query"
    }
    OR (if no agent matches / general queries / web queries / general knowledge):
    {
      "selected_agent": "None",
      "reason": "Explanation",
      "answer": "Direct response to the user"
    }
    "**Examples**:"
        "Query 1: 'What is the dress code policy for employees?' →\n"
        '{ "selected_agent": "RAG_Agent", "reason": "The query asks for the dress code policy, which is available in internal documents." }'
        "Query 2: 'Search industry salary trends for ML Engineer' →\n"
        '{ "selected_agent": "None", "reason": "This requires external knowledge/web search, so it is handled directly." }'

    Avalible Docs in RAG:
        "Mobile Phone Allowance Policy v5.pdf": ,
        "Pership Dress Code Policy.pdf": ,
        "Pership Group ICT Policy -v3.pdf": ,
        "FINANCE Standard Operating Procedures.pdf":,
        "Pership Holdings Q&A 02.pdf":[Specifically tell that this contenines information from internet sources upto 2022],
        "Pership Holdings Overview.pdf":[General overview of Pership Holdings using internet sources upto 2022],
            
    """

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    
    json_res = json.loads(response.choices[0].message.content)
    # print(json)
    if json_res["selected_agent"] == "None":
        Agent_none = True
    else:
        Agent_none = False    
    
    return json_res,Agent_none