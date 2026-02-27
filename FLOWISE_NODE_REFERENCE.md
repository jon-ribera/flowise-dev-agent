# Flowise Node Schema Reference

**Generated:** 2026-02-10  
**Total Nodes:** 303  
**Categories:** 24

This reference documents every node available in the Flowise instance, including required inputs, optional parameters, credential requirements, and base classes. Use this when programmatically building chatflows via the Flowise MCP tools.

---

## Table of Contents

- [Agent Flows (15)](#agent-flows-15)
- [Agents (12)](#agents-12)
- [Cache (7)](#cache-7)
- [Chains (13)](#chains-13)
- [Chat Models (37)](#chat-models-37)
- [Document Loaders (41)](#document-loaders-41)
- [Embeddings (17)](#embeddings-17)
- [Engine (4)](#engine-4)
- [Graph (1)](#graph-1)
- [LLMs (13)](#llms-13)
- [Memory (15)](#memory-15)
- [Moderation (2)](#moderation-2)
- [Multi Agents (2)](#multi-agents-2)
- [Output Parsers (4)](#output-parsers-4)
- [Prompts (3)](#prompts-3)
- [Record Manager (3)](#record-manager-3)
- [Response Synthesizer (4)](#response-synthesizer-4)
- [Retrievers (15)](#retrievers-15)
- [Sequential Agents (11)](#sequential-agents-11)
- [Text Splitters (6)](#text-splitters-6)
- [Tools (39)](#tools-39)
- [Tools (MCP) (8)](#tools-mcp-8)
- [Utilities (5)](#utilities-5)
- [Vector Stores (26)](#vector-stores-26)

---

## Agent Flows (15)

### Agent (`agentAgentflow`)

**Version:** 3.2  
**Description:** Dynamically choose and utilize tools during runtime, enabling multi-step reasoning  
**Base Classes:** `Agent`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `agentModel` | asyncOptions |  | Model |
| `agentMessages` | array |  | Messages |
| `agentToolsBuiltInOpenAI` | multiOptions |  | OpenAI Built-in Tools |
| `agentToolsBuiltInGemini` | multiOptions |  | Gemini Built-in Tools |
| `agentToolsBuiltInAnthropic` | multiOptions |  | Anthropic Built-in Tools |
| `agentTools` | array |  | Tools |
| `agentKnowledgeDocumentStores` | array |  | Give your agent context about different document sources. Document stores must be upserted in advanc |
| `agentKnowledgeVSEmbeddings` | array |  | Give your agent context about different document sources from existing vector stores and embeddings |
| `agentEnableMemory` | boolean | True | Enable memory for the conversation thread |
| `agentMemoryType` | options | allMessages | Memory Type |
| `agentMemoryWindowSize` | number | 20 | Uses a fixed window size to surface the last N messages |
| `agentMemoryMaxTokenLimit` | number | 2000 | Summarize conversations once token limit is reached. Default to 2000 |
| `agentUserMessage` | string |  | Add an input message as user message at the end of the conversation |
| `agentReturnResponseAs` | options | userMessage | Return Response As |
| `agentStructuredOutput` | array |  | Instruct the Agent to give output in a JSON structured schema |
| `agentUpdateState` | array |  | Update runtime state during the execution of the workflow |

---

### Condition Agent (`conditionAgentAgentflow`)

**Version:** 1.1  
**Description:** Utilize an agent to split flows based on dynamic conditions  
**Base Classes:** `ConditionAgent`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `conditionAgentModel` | asyncOptions |  | Model |
| `conditionAgentInstructions` | string |  | A general instructions of what the condition agent should do |
| `conditionAgentInput` | string | <p><span class="variable" data-type="mention" data-id="question" data-label="question">{{ question }}</span> </p> | Input to be used for the condition agent |
| `conditionAgentScenarios` | array | [{'scenario': ''}, {'scenario': ''}] | Define the scenarios that will be used as the conditions to split the flow |
| `conditionAgentOverrideSystemPrompt` | boolean |  | Override initial system prompt for Condition Agent |
| `conditionAgentSystemPrompt` | string | <p>You are part of a multi-agent system designed to make agent coordination and execution easy. Your task is to analyze the given input and select one matching scenario from a provided set of scenarios.</p>
    <ul>
        <li><strong>Input</strong>: A string representing the user's query, message or data.</li>
        <li><strong>Scenarios</strong>: A list of predefined scenarios that relate to the input.</li>
        <li><strong>Instruction</strong>: Determine which of the provided scenarios is the best fit for the input.</li>
    </ul>
    <h2>Steps</h2>
    <ol>
        <li><strong>Read the input string</strong> and the list of scenarios.</li>
        <li><strong>Analyze the content of the input</strong> to identify its main topic or intention.</li>
        <li><strong>Compare the input with each scenario</strong>: Evaluate how well the input's topic or intention aligns with each of the provided scenarios and select the one that is the best fit.</li>
        <li><strong>Output the result</strong>: Return the selected scenario in the specified JSON format.</li>
    </ol>
    <h2>Output Format</h2>
    <p>Output should be a JSON object that names the selected scenario, like this: <code>{"output": "<selected_scenario_name>"}</code>. No explanation is needed.</p>
    <h2>Examples</h2>
    <ol>
       <li>
            <p><strong>Input</strong>: <code>{"input": "Hello", "scenarios": ["user is asking about AI", "user is not asking about AI"], "instruction": "Your task is to check if the user is asking about AI."}</code></p>
            <p><strong>Output</strong>: <code>{"output": "user is not asking about AI"}</code></p>
        </li>
        <li>
            <p><strong>Input</strong>: <code>{"input": "What is AIGC?", "scenarios": ["user is asking about AI", "user is asking about the weather"], "instruction": "Your task is to check and see if the user is asking a topic about AI."}</code></p>
            <p><strong>Output</strong>: <code>{"output": "user is asking about AI"}</code></p>
        </li>
        <li>
            <p><strong>Input</strong>: <code>{"input": "Can you explain deep learning?", "scenarios": ["user is interested in AI topics", "user wants to order food"], "instruction": "Determine if the user is interested in learning about AI."}</code></p>
            <p><strong>Output</strong>: <code>{"output": "user is interested in AI topics"}</code></p>
        </li>
    </ol>
    <h2>Note</h2>
    <ul>
        <li>Ensure that the input scenarios align well with potential user queries for accurate matching.</li>
        <li>DO NOT include anything other than the JSON in your response.</li>
    </ul> | Expert use only. Modifying this can significantly alter agent behavior. Leave default if unsure |

---

### Condition (`conditionAgentflow`)

**Version:** 1  
**Description:** Split flows based on If Else conditions  
**Base Classes:** `Condition`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `conditions` | array | [{'type': 'string', 'value1': '', 'operation': 'equal', 'value2': ''}] | Values to compare |

---

### Custom Function (`customFunctionAgentflow`)

**Version:** 1.1  
**Description:** Execute custom function  
**Base Classes:** `CustomFunction`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `customFunctionInputVariables` | array |  | Input variables can be used in the function with prefix $. For example: $foo |
| `customFunctionJavascriptFunction` | code |  | The function to execute. Must return a string or an object that can be converted to a string. |
| `customFunctionUpdateState` | array |  | Update runtime state during the execution of the workflow |

---

### Direct Reply (`directReplyAgentflow`)

**Version:** 1  
**Description:** Directly reply to the user with a message  
**Base Classes:** `DirectReply`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `directReplyMessage` | string |  | Message |

---

### Execute Flow (`executeFlowAgentflow`)

**Version:** 1.2  
**Description:** Execute another flow  
**Base Classes:** `ExecuteFlow`  

**Credential Required:** Connect Credential (chatflowApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `executeFlowSelectedFlow` | asyncOptions |  | Select Flow |
| `executeFlowInput` | string |  | Input |
| `executeFlowOverrideConfig` | json |  | Override the config passed to the flow |
| `executeFlowBaseURL` | string |  | Base URL to Flowise. By default, it is the URL of the incoming request. Useful when you need to exec |
| `executeFlowReturnResponseAs` | options | userMessage | Return Response As |
| `executeFlowUpdateState` | array |  | Update runtime state during the execution of the workflow |

---

### HTTP (`httpAgentflow`)

**Version:** 1.1  
**Description:** Send a HTTP request  
**Base Classes:** `HTTP`  

**Credential Required:** HTTP Credential (httpBasicAuth, httpBearerToken, httpApiKey)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `method` | options | GET | Method |
| `url` | string |  | URL |
| `headers` | array |  | Headers |
| `queryParams` | array |  | Query Params |
| `bodyType` | options |  | Body Type |
| `body` | string |  | Body |
| `body` | array |  | Body |
| `responseType` | options |  | Response Type |

---

### Human Input (`humanInputAgentflow`)

**Version:** 1  
**Description:** Request human input, approval or rejection during execution  
**Base Classes:** `HumanInput`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `humanInputDescriptionType` | options |  | Description Type |
| `humanInputDescription` | string |  | Description |
| `humanInputModel` | asyncOptions |  | Model |
| `humanInputModelPrompt` | string | <p>Summarize the conversation between the user and the assistant, reiterate the last message from the assistant, and ask if user would like to proceed or if they have any feedback. </p>
<ul>
<li>Begin by capturing the key points of the conversation, ensuring that you reflect the main ideas and themes discussed.</li>
<li>Then, clearly reproduce the last message sent by the assistant to maintain continuity. Make sure the whole message is reproduced.</li>
<li>Finally, ask the user if they would like to proceed, or provide any feedback on the last assistant message</li>
</ul>
<h2 id="output-format-the-output-should-be-structured-in-three-parts-">Output Format The output should be structured in three parts in text:</h2>
<ul>
<li>A summary of the conversation (1-3 sentences).</li>
<li>The last assistant message (exactly as it appeared).</li>
<li>Ask the user if they would like to proceed, or provide any feedback on last assistant message. No other explanation and elaboration is needed.</li>
</ul>
 | Prompt |
| `humanInputEnableFeedback` | boolean | True | Enable Feedback |

---

### Iteration (`iterationAgentflow`)

**Version:** 1  
**Description:** Execute the nodes within the iteration block through N iterations  
**Base Classes:** `Iteration`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `iterationInput` | string |  | The input array to iterate over |

---

### LLM (`llmAgentflow`)

**Version:** 1.1  
**Description:** Large language models to analyze user-provided inputs and generate responses  
**Base Classes:** `LLM`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `llmModel` | asyncOptions |  | Model |
| `llmMessages` | array |  | Messages |
| `llmEnableMemory` | boolean | True | Enable memory for the conversation thread |
| `llmMemoryType` | options | allMessages | Memory Type |
| `llmMemoryWindowSize` | number | 20 | Uses a fixed window size to surface the last N messages |
| `llmMemoryMaxTokenLimit` | number | 2000 | Summarize conversations once token limit is reached. Default to 2000 |
| `llmUserMessage` | string |  | Add an input message as user message at the end of the conversation |
| `llmReturnResponseAs` | options | userMessage | Return Response As |
| `llmStructuredOutput` | array |  | Instruct the LLM to give output in a JSON structured schema |
| `llmUpdateState` | array |  | Update runtime state during the execution of the workflow |

---

### Loop (`loopAgentflow`)

**Version:** 1.2  
**Description:** Loop back to a previous node  
**Base Classes:** `Loop`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `loopBackToNode` | asyncOptions |  | Loop Back To |
| `maxLoopCount` | number | 5 | Max Loop Count |
| `fallbackMessage` | string |  | Message to display if the loop count is exceeded |
| `loopUpdateState` | array |  | Update runtime state during the execution of the workflow |

---

### Retriever (`retrieverAgentflow`)

**Version:** 1.1  
**Description:** Retrieve information from vector database  
**Base Classes:** `Retriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `retrieverKnowledgeDocumentStores` | array |  | Document stores to retrieve information from. Document stores must be upserted in advance. |
| `retrieverQuery` | string |  | Retriever Query |
| `outputFormat` | options | text | Output Format |
| `retrieverUpdateState` | array |  | Update runtime state during the execution of the workflow |

---

### Start (`startAgentflow`)

**Version:** 1.1  
**Description:** Starting point of the agentflow  
**Base Classes:** `Start`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `startInputType` | options | chatInput | Input Type |
| `formTitle` | string |  | Form Title |
| `formDescription` | string |  | Form Description |
| `formInputTypes` | array |  | Specify the type of form input |
| `startEphemeralMemory` | boolean |  | Start fresh for every execution without past chat history |
| `startState` | array |  | Runtime state during the execution of the workflow |
| `startPersistState` | boolean |  | Persist the state in the same session |

---

### Sticky Note (`stickyNoteAgentflow`)

**Version:** 1  
**Description:** Add notes to the agent flow  
**Base Classes:** `StickyNote`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `note` | string |  |  |

---

### Tool (`toolAgentflow`)

**Version:** 1.2  
**Description:** Tools allow LLM to interact with external systems  
**Base Classes:** `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `toolAgentflowSelectedTool` | asyncOptions |  | Tool |
| `toolInputArgs` | array |  | Tool Input Arguments |
| `toolUpdateState` | array |  | Update runtime state during the execution of the workflow |

---

## Agents (12)

### Airtable Agent (`airtableAgent`)

**Version:** 2  
**Description:** Agent used to answer queries on Airtable table  
**Base Classes:** `AgentExecutor`, `BaseChain`, `Runnable`  

**Credential Required:** Connect Credential (airtableApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `baseId` | string |  | If your table URL looks like: https://airtable.com/app11RobdGoX0YNsC/tblJdmvbrgizbYICO/viw9UrP77Id0C |
| `tableId` | string |  | If your table URL looks like: https://airtable.com/app11RobdGoX0YNsC/tblJdmvbrgizbYICO/viw9UrP77Id0C |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `returnAll` | boolean | True | If all results should be returned or only up to a given limit |
| `limit` | number | 100 | Number of results to return |

</details>

---

### Anthropic Agent (`anthropicAgentLlamaIndex`)

**Version:** 1  
**Description:** Agent that uses Anthropic Claude Function Calling to pick the tools and args to call using LlamaIndex  
**Base Classes:** `AnthropicAgent`, `AgentRunner`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool_LlamaIndex |  | Tools |
| `memory` | BaseChatMemory |  | Memory |
| `model` | BaseChatModel_LlamaIndex |  | Anthropic Claude Model |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessage` | string |  | System Message |

</details>

---

### AutoGPT (`autoGPT`)

**Version:** 2  
**Description:** Autonomous agent with chain of thoughts for self-guided task completion  
**Base Classes:** `AutoGPT`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool |  | Allowed Tools |
| `model` | BaseChatModel |  | Chat Model |
| `vectorStoreRetriever` | BaseRetriever |  | Vector Store Retriever |
| `aiName` | string |  | AutoGPT Name |
| `aiRole` | string |  | AutoGPT Role |
| `maxLoop` | number | 5 | Maximum Loop |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

---

### BabyAGI (`babyAGI`)

**Version:** 2  
**Description:** Task Driven Autonomous Agent which creates new task and reprioritizes task list based on objective  
**Base Classes:** `BabyAGI`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel |  | Chat Model |
| `vectorStore` | VectorStore |  | Vector Store |
| `taskLoop` | number | 3 | Task Loop |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

---

### Conversational Agent (`conversationalAgent`)

**Version:** 3  
**Description:** Conversational agent for a chat model. It will utilize chat specific prompts  
**Base Classes:** `AgentExecutor`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool |  | Allowed Tools |
| `model` | BaseChatModel |  | Chat Model |
| `memory` | BaseChatMemory |  | Memory |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessage` | string | Assistant is a large language model trained by OpenAI.

Assistant is designed to be able to assist with a wide range of tasks, from answering simple questions to providing in-depth explanations and discussions on a wide range of topics. As a language model, Assistant is able to generate human-like text based on the input it receives, allowing it to engage in natural-sounding conversations and provide responses that are coherent and relevant to the topic at hand.

Assistant is constantly learning and improving, and its capabilities are constantly evolving. It is able to process and understand large amounts of text, and can use this knowledge to provide accurate and informative responses to a wide range of questions. Additionally, Assistant is able to generate its own text based on the input it receives, allowing it to engage in discussions and provide explanations and descriptions on a wide range of topics.

Overall, Assistant is a powerful system that can help with a wide range of tasks and provide valuable insights and information on a wide range of topics. Whether you need help with a specific question or just want to have a conversation about a particular topic, Assistant is here to assist. | System Message |
| `maxIterations` | number |  | Max Iterations |

</details>

---

### CSV Agent (`csvAgent`)

**Version:** 3  
**Description:** Agent used to answer queries on CSV data  
**Base Classes:** `AgentExecutor`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `csvFile` | file |  | Csv File |
| `model` | BaseLanguageModel |  | Language Model |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessagePrompt` | string |  | System Message |
| `customReadCSV` | code | read_csv(csv_data) | Custom Pandas <a target="_blank" href="https://pandas.pydata.org/pandas-docs/stable/reference/api/pa |

</details>

---

### OpenAI Assistant (`openAIAssistant`)

**Version:** 4  
**Description:** An agent that uses OpenAI Assistant API to pick the tool and args to call  
**Base Classes:** `OpenAIAssistant`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `selectedAssistant` | asyncOptions |  | Select Assistant |
| `tools` | Tool |  | Allowed Tools |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `toolChoice` | string |  | Controls which (if any) tool is called by the model. Can be "none", "auto", "required", or the name  |
| `parallelToolCalls` | boolean | True | Whether to enable parallel function calling during tool use. Defaults to true |
| `disableFileDownload` | boolean |  | Messages can contain text, images, or files. In some cases, you may want to prevent others from down |

</details>

---

### OpenAI Tool Agent (`openAIToolAgentLlamaIndex`)

**Version:** 2  
**Description:** Agent that uses OpenAI Function Calling to pick the tools and args to call using LlamaIndex  
**Base Classes:** `OpenAIToolAgent`, `AgentRunner`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool_LlamaIndex |  | Tools |
| `memory` | BaseChatMemory |  | Memory |
| `model` | BaseChatModel_LlamaIndex |  | OpenAI/Azure Chat Model |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessage` | string |  | System Message |

</details>

---

### ReAct Agent for Chat Models (`reactAgentChat`)

**Version:** 4  
**Description:** Agent that uses the ReAct logic to decide what action to take, optimized to be used with Chat Models  
**Base Classes:** `AgentExecutor`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool |  | Allowed Tools |
| `model` | BaseChatModel |  | Chat Model |
| `memory` | BaseChatMemory |  | Memory |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxIterations` | number |  | Max Iterations |

</details>

---

### ReAct Agent for LLMs (`reactAgentLLM`)

**Version:** 2  
**Description:** Agent that uses the ReAct logic to decide what action to take, optimized to be used with LLMs  
**Base Classes:** `AgentExecutor`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool |  | Allowed Tools |
| `model` | BaseLanguageModel |  | Language Model |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxIterations` | number |  | Max Iterations |

</details>

---

### Tool Agent (`toolAgent`)

**Version:** 2  
**Description:** Agent that uses Function Calling to pick the tools and args to call  
**Base Classes:** `AgentExecutor`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool |  | Tools |
| `memory` | BaseChatMemory |  | Memory |
| `model` | BaseChatModel |  | Only compatible with models that are capable of function calling: ChatOpenAI, ChatMistral, ChatAnthr |
| `chatPromptTemplate` | ChatPromptTemplate |  | Override existing prompt with Chat Prompt Template. Human Message must includes {input} variable |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessage` | string | You are a helpful AI assistant. | If Chat Prompt Template is provided, this will be ignored |
| `maxIterations` | number |  | Max Iterations |
| `enableDetailedStreaming` | boolean | False | Stream detailed intermediate steps during agent execution |

</details>

---

### XML Agent (`xmlAgent`)

**Version:** 2  
**Description:** Agent that is designed for LLMs that are good for reasoning/writing XML (e.g: Anthropic Claude)  
**Base Classes:** `XMLAgent`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool |  | Tools |
| `memory` | BaseChatMemory |  | Memory |
| `model` | BaseChatModel |  | Chat Model |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessage` | string | You are a helpful assistant. Help the user answer any questions.

You have access to the following tools:

{tools}

In order to use a tool, you can use <tool></tool> and <tool_input></tool_input> tags. You will then get back a response in the form <observation></observation>
For example, if you have a tool called 'search' that could run a google search, in order to search for the weather in SF you would respond:

<tool>search</tool><tool_input>weather in SF</tool_input>
<observation>64 degrees</observation>

When you are done, respond with a final answer between <final_answer></final_answer>. For example:

<final_answer>The weather in SF is 64 degrees</final_answer>

Begin!

Previous Conversation:
{chat_history}

Question: {input}
{agent_scratchpad} | System Message |
| `maxIterations` | number |  | Max Iterations |

</details>

---

## Cache (7)

### Google GenAI Context Cache (`googleGenerativeAIContextCache`)

**Version:** 1  
**Description:** Large context cache for Google Gemini large language models  
**Base Classes:** `GoogleAICacheManager`, `GoogleAICacheManager`  

**Credential Required:** Connect Credential (googleGenerativeAI)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `ttl` | number | 2592000 | TTL |

---

### InMemory Cache (`inMemoryCache`)

**Version:** 1  
**Description:** Cache LLM response in memory, will be cleared once app restarted  
**Base Classes:** `InMemoryCache`, `BaseCache`  

*No configurable inputs.*

---

### InMemory Embedding Cache (`inMemoryEmbeddingCache`)

**Version:** 1  
**Description:** Cache generated Embeddings in memory to avoid needing to recompute them.  
**Base Classes:** `InMemoryEmbeddingCache`, `Embeddings`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `embeddings` | Embeddings |  | Embeddings |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `namespace` | string |  | Namespace |

</details>

---

### Momento Cache (`momentoCache`)

**Version:** 1  
**Description:** Cache LLM response using Momento, a distributed, serverless cache  
**Base Classes:** `MomentoCache`, `BaseCache`  

**Credential Required:** Connect Credential (momentoCacheApi)

*No configurable inputs.*

---

### Redis Cache (`redisCache`)

**Version:** 1  
**Description:** Cache LLM response in Redis, useful for sharing cache across multiple processes or servers  
**Base Classes:** `RedisCache`, `BaseCache`  

**Credential Required:** Connect Credential (redisCacheApi, redisCacheUrlApi)

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `ttl` | number |  | Time to Live (ms) |

</details>

---

### Redis Embeddings Cache (`redisEmbeddingsCache`)

**Version:** 1  
**Description:** Cache generated Embeddings in Redis to avoid needing to recompute them.  
**Base Classes:** `RedisEmbeddingsCache`, `Embeddings`  

**Credential Required:** Connect Credential (redisCacheApi, redisCacheUrlApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `embeddings` | Embeddings |  | Embeddings |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `ttl` | number | 3600 | Time to Live (ms) |
| `namespace` | string |  | Namespace |

</details>

---

### Upstash Redis Cache (`upstashRedisCache`)

**Version:** 1  
**Description:** Cache LLM response in Upstash Redis, serverless data for Redis and Kafka  
**Base Classes:** `UpstashRedisCache`, `BaseCache`  

**Credential Required:** Connect Credential (upstashRedisApi)

*No configurable inputs.*

---

## Chains (13)

### Conversation Chain (`conversationChain`)

**Version:** 3  
**Description:** Chat models specific conversational chain with memory  
**Base Classes:** `ConversationChain`, `LLMChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel |  | Chat Model |
| `memory` | BaseMemory |  | Memory |
| `chatPromptTemplate` | ChatPromptTemplate |  | Override existing prompt with Chat Prompt Template. Human Message must includes {input} variable |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessagePrompt` | string | The following is a friendly conversation between a human and an AI. The AI is talkative and provides lots of specific details from its context. If the AI does not know the answer to a question, it truthfully says it does not know. | If Chat Prompt Template is provided, this will be ignored |

</details>

---

### Conversational Retrieval QA Chain (`conversationalRetrievalQAChain`)

**Version:** 3  
**Description:** Document QA - built on RetrievalQAChain to provide a chat history component  
**Base Classes:** `ConversationalRetrievalQAChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel |  | Chat Model |
| `vectorStoreRetriever` | BaseRetriever |  | Vector Store Retriever |
| `memory` | BaseMemory |  | If left empty, a default BufferMemory will be used |
| `returnSourceDocuments` | boolean |  | Return Source Documents |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `rephrasePrompt` | string | Given the following conversation and a follow up question, rephrase the follow up question to be a standalone question.

Chat History:
{chat_history}
Follow Up Input: {question}
Standalone Question: | Using previous chat history, rephrase question into a standalone question |
| `responsePrompt` | string | I want you to act as a document that I am having a conversation with. Your name is "AI Assistant". Using the provided context, answer the user's question to the best of your ability using the resources provided.
If there is nothing in the context relevant to the question at hand, just say "Hmm, I'm not sure" and stop after that. Refuse to answer any question not about the info. Never break character.
------------
{context}
------------
REMEMBER: If there is no relevant information within the context, just say "Hmm, I'm not sure". Don't try to make up an answer. Never break character. | Taking the rephrased question, search for answer from the provided context |

</details>

---

### GET API Chain (`getApiChain`)

**Version:** 1  
**Description:** Chain to run queries against GET API  
**Base Classes:** `GETApiChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `apiDocs` | string |  | Description of how API works. Please refer to more <a target="_blank" href="https://github.com/langc |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `headers` | json |  | Headers |
| `urlPrompt` | string | You are given the below API Documentation:
{api_docs}
Using this documentation, generate the full API url to call for answering the user question.
You should build the API url in order to get a response that is as short as possible, while still getting the necessary information to answer the question. Pay attention to deliberately exclude any unnecessary pieces of data in the API call.

Question:{question}
API url: | Prompt used to tell LLMs how to construct the URL. Must contains {api_docs} and {question} |
| `ansPrompt` | string | Given this {api_response} response for {api_url}. use the given response to answer this {question} | Prompt used to tell LLMs how to return the API response. Must contains {api_response}, {api_url}, an |

</details>

---

### Graph Cypher QA Chain (`graphCypherQAChain`)

**Version:** 1.1  
**Description:** Advanced chain for question-answering against a Neo4j graph by generating Cypher statements  
**Base Classes:** `GraphCypherQAChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Model for generating Cypher queries and answers. |
| `graph` | Neo4j |  | Neo4j Graph |
| `cypherPrompt` | BasePromptTemplate |  | Prompt template for generating Cypher queries. Must include {schema} and {question} variables. If no |
| `cypherModel` | BaseLanguageModel |  | Model for generating Cypher queries. If not provided, the main model will be used. |
| `qaPrompt` | BasePromptTemplate |  | Prompt template for generating answers. Must include {context} and {question} variables. If not prov |
| `qaModel` | BaseLanguageModel |  | Model for generating answers. If not provided, the main model will be used. |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |
| `returnDirect` | boolean | False | If true, return the raw query results instead of using the QA chain |

---

### LLM Chain (`llmChain`)

**Version:** 3  
**Description:** Chain to run queries against LLMs  
**Base Classes:** `LLMChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `prompt` | BasePromptTemplate |  | Prompt |
| `outputParser` | BaseLLMOutputParser |  | Output Parser |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |
| `chainName` | string |  | Chain Name |

---

### Multi Prompt Chain (`multiPromptChain`)

**Version:** 2  
**Description:** Chain automatically picks an appropriate prompt from multiple prompt templates  
**Base Classes:** `MultiPromptChain`, `MultiRouteChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `promptRetriever` | PromptRetriever |  | Prompt Retriever |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

---

### Multi Retrieval QA Chain (`multiRetrievalQAChain`)

**Version:** 2  
**Description:** QA Chain that automatically picks an appropriate vector store from multiple retrievers  
**Base Classes:** `MultiRetrievalQAChain`, `MultiRouteChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `vectorStoreRetriever` | VectorStoreRetriever |  | Vector Store Retriever |
| `returnSourceDocuments` | boolean |  | Return Source Documents |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

---

### OpenAPI Chain (`openApiChain`)

**Version:** 2  
**Description:** Chain that automatically select and call APIs based only on an OpenAPI spec  
**Base Classes:** `OpenAPIChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel |  | Chat Model |
| `yamlLink` | string |  | If YAML link is provided, uploaded YAML File will be ignored and YAML link will be used instead |
| `yamlFile` | file |  | If YAML link is provided, uploaded YAML File will be ignored and YAML link will be used instead |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `headers` | json |  | Headers |

</details>

---

### POST API Chain (`postApiChain`)

**Version:** 1  
**Description:** Chain to run queries against POST API  
**Base Classes:** `POSTApiChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `apiDocs` | string |  | Description of how API works. Please refer to more <a target="_blank" href="https://github.com/langc |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `headers` | json |  | Headers |
| `urlPrompt` | string | You are given the below API Documentation:
{api_docs}
Using this documentation, generate a json string with two keys: "url" and "data".
The value of "url" should be a string, which is the API url to call for answering the user question.
The value of "data" should be a dictionary of key-value pairs you want to POST to the url as a JSON body.
Be careful to always use double quotes for strings in the json string.
You should build the json string in order to get a response that is as short as possible, while still getting the necessary information to answer the question. Pay attention to deliberately exclude any unnecessary pieces of data in the API call.

Question:{question}
json string: | Prompt used to tell LLMs how to construct the URL. Must contains {api_docs} and {question} |
| `ansPrompt` | string | You are given the below API Documentation:
{api_docs}
Using this documentation, generate a json string with two keys: "url" and "data".
The value of "url" should be a string, which is the API url to call for answering the user question.
The value of "data" should be a dictionary of key-value pairs you want to POST to the url as a JSON body.
Be careful to always use double quotes for strings in the json string.
You should build the json string in order to get a response that is as short as possible, while still getting the necessary information to answer the question. Pay attention to deliberately exclude any unnecessary pieces of data in the API call.

Question:{question}
json string: {api_url_body}

Here is the response from the API:

{api_response}

Summarize this response to answer the original question.

Summary: | Prompt used to tell LLMs how to return the API response. Must contains {api_response}, {api_url}, an |

</details>

---

### Retrieval QA Chain (`retrievalQAChain`)

**Version:** 2  
**Description:** QA chain to answer a question based on the retrieved documents  
**Base Classes:** `RetrievalQAChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `vectorStoreRetriever` | BaseRetriever |  | Vector Store Retriever |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

---

### Sql Database Chain (`sqlDatabaseChain`)

**Version:** 5  
**Description:** Answer questions over a SQL database  
**Base Classes:** `SqlDatabaseChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `database` | options | sqlite | Database |
| `url` | string |  | Connection string or file path (sqlite only) |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `includesTables` | string |  | Tables to include for queries, separated by comma. Can only use Include Tables or Ignore Tables |
| `ignoreTables` | string |  | Tables to ignore for queries, separated by comma. Can only use Ignore Tables or Include Tables |
| `sampleRowsInTableInfo` | number |  | Number of sample row for tables to load for info. |
| `topK` | number |  | If you are querying for several rows of a table you can select the maximum number of results you wan |
| `customPrompt` | string |  | You can provide custom prompt to the chain. This will override the existing default prompt used. See |

</details>

---

### Vectara QA Chain (`vectaraQAChain`)

**Version:** 2  
**Description:** QA chain for Vectara  
**Base Classes:** `VectaraQAChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `vectaraStore` | VectorStore |  | Vectara Store |
| `summarizerPromptName` | options | vectara-summary-ext-v1.2.0 | Summarize the results fetched from Vectara. Read <a target="_blank" href="https://docs.vectara.com/d |
| `responseLang` | options | eng | Return the response in specific language. If not selected, Vectara will automatically detects the la |
| `maxSummarizedResults` | number | 7 | Maximum results used to build the summarized response |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

---

### VectorDB QA Chain (`vectorDBQAChain`)

**Version:** 2  
**Description:** QA chain for vector databases  
**Base Classes:** `VectorDBQAChain`, `BaseChain`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `vectorStore` | VectorStore |  | Vector Store |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

---

## Chat Models (37)

### AWS ChatBedrock (`awsChatBedrock`)

**Version:** 6.1  
**Description:** Wrapper around AWS Bedrock large language models that use the Converse API  
**Base Classes:** `AWSChatBedrock`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** AWS Credential (awsApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `region` | asyncOptions | us-east-1 | Region |
| `model` | asyncOptions | anthropic.claude-3-haiku-20240307-v1:0 | Model Name |
| `customModel` | string |  | If provided, will override model selected from Model Name option |
| `endpointHost` | string |  | Custom endpoint host to use for the model. If provided, will override the default endpoint host. |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `temperature` | number | 0.7 | Temperature parameter may not apply to certain model. Please check available model parameters |
| `max_tokens_to_sample` | number | 200 | Max Tokens parameter may not apply to certain model. Please check available model parameters |
| `latencyOptimized` | boolean | False | Enable latency optimized configuration for supported models. Refer to the supported <a href="https:/ |

</details>

---

### Azure ChatOpenAI (`azureChatOpenAI`)

**Version:** 7.1  
**Description:** Wrapper around Azure OpenAI large language models that use the Chat endpoint  
**Base Classes:** `AzureChatOpenAI`, `ChatOpenAI`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (azureOpenAIApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `imageResolution` | options | low | This parameter controls the resolution in which the model views the image. |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions |  | Model Name |
| `temperature` | number | 0.9 | Temperature |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (12 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Max Tokens |
| `streaming` | boolean | True | Streaming |
| `topP` | number |  | Top Probability |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |
| `baseOptions` | json |  | BaseOptions |
| `imageResolution` | options | low | This parameter controls the resolution in which the model views the image. |
| `reasoning` | boolean | False | Whether the model supports reasoning. Only applicable for reasoning models. |
| `reasoningEffort` | options |  | Constrains effort on reasoning for reasoning models. Only applicable for o1 and o3 models. |
| `reasoningSummary` | options |  | A summary of the reasoning performed by the model. This can be useful for debugging and understandin |

</details>

---

### AzureChatOpenAI (`azureChatOpenAI_LlamaIndex`)

**Version:** 2  
**Description:** Wrapper around Azure OpenAI Chat LLM specific for LlamaIndex  
**Base Classes:** `AzureChatOpenAI`, `BaseChatModel_LlamaIndex`, `ToolCallLLM`, `BaseLLM`  

**Credential Required:** Connect Credential (azureOpenAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | gpt-3.5-turbo-16k | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `timeout` | number |  | Timeout |

</details>

---

### ChatAlibabaTongyi (`chatAlibabaTongyi`)

**Version:** 2  
**Description:** Wrapper around Alibaba Tongyi Chat Endpoints  
**Base Classes:** `ChatAlibabaTongyi`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (AlibabaApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Model |
| `temperature` | number | 0.9 | Temperature |
| `streaming` | boolean | True | Streaming |

---

### ChatAnthropic (`chatAnthropic`)

**Version:** 8  
**Description:** Wrapper around ChatAnthropic large language models that use the Chat endpoint  
**Base Classes:** `ChatAnthropic`, `ChatAnthropicMessages`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (anthropicApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | claude-3-haiku | Model Name |
| `temperature` | number | 0.9 | Temperature |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokensToSample` | number |  | Max Tokens |
| `topP` | number |  | Top P |
| `topK` | number |  | Top K |
| `extendedThinking` | boolean |  | Enable extended thinking for reasoning model such as Claude Sonnet 3.7 and Claude 4 |
| `budgetTokens` | number | 1024 | Maximum number of tokens Claude is allowed use for its internal reasoning process |

</details>

---

### ChatAnthropic (`chatAnthropic_LlamaIndex`)

**Version:** 3  
**Description:** Wrapper around ChatAnthropic LLM specific for LlamaIndex  
**Base Classes:** `ChatAnthropic`, `BaseChatModel_LlamaIndex`, `ToolCallLLM`, `BaseLLM`  

**Credential Required:** Connect Credential (anthropicApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | claude-3-haiku | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokensToSample` | number |  | Max Tokens |
| `topP` | number |  | Top P |

</details>

---

### ChatBaiduWenxin (`chatBaiduWenxin`)

**Version:** 2  
**Description:** Wrapper around BaiduWenxin Chat Endpoints  
**Base Classes:** `ChatBaiduWenxin`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (baiduQianfanApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Model |
| `temperature` | number | 0.9 | Temperature |
| `streaming` | boolean | True | Streaming |

---

### ChatCerebras (`chatCerebras`)

**Version:** 3  
**Description:** Wrapper around Cerebras Inference API  
**Base Classes:** `ChatCerebras`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (cerebrasAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | llama3.1-8b | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `timeout` | number |  | Timeout |
| `basepath` | string | https://api.cerebras.ai/v1 | BasePath |
| `baseOptions` | json |  | BaseOptions |

</details>

---

### ChatCloudflareWorkersAI (`chatCloudflareWorkersAI`)

**Version:** 1  
**Description:** Wrapper around Cloudflare Workers AI chat models  
**Base Classes:** `ChatCloudflareWorkersAI`, `SimpleChatModel`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (cloudflareApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | string | @cf/meta/llama-3.1-8b-instruct-fast | Model to use, e.g. @cf/meta/llama-3.1-8b-instruct-fast |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `baseUrl` | string |  | Base URL for Cloudflare Workers AI. Defaults to https://api.cloudflare.com/client/v4/accounts |

</details>

---

### ChatCohere (`chatCohere`)

**Version:** 2  
**Description:** Wrapper around Cohere Chat Endpoints  
**Base Classes:** `ChatCohere`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (cohereApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | command-r | Model Name |
| `temperature` | number | 0.7 | Temperature |
| `streaming` | boolean | True | Streaming |

---

### ChatCometAPI (`chatCometAPI`)

**Version:** 1  
**Description:** Wrapper around CometAPI large language models that use the Chat endpoint  
**Base Classes:** `ChatCometAPI`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (cometApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string | gpt-5-mini | Enter the model name (e.g., gpt-5-mini, claude-sonnet-4-20250514, gemini-2.0-flash) |
| `temperature` | number | 0.7 | Temperature |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `baseOptions` | json |  | Additional options to pass to the CometAPI client. This should be a JSON object. |

</details>

---

### ChatDeepseek (`chatDeepseek`)

**Version:** 1  
**Description:** Wrapper around Deepseek large language models that use the Chat endpoint  
**Base Classes:** `chatDeepseek`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (deepseekApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | deepseek-chat | Model Name |
| `temperature` | number | 0.7 | Temperature |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `timeout` | number |  | Timeout |
| `stopSequence` | string |  | List of stop words to use when generating. Use comma to separate multiple stop words. |
| `baseOptions` | json |  | Additional options to pass to the Deepseek client. This should be a JSON object. |

</details>

---

### ChatFireworks (`chatFireworks`)

**Version:** 2  
**Description:** Wrapper around Fireworks Chat Endpoints  
**Base Classes:** `ChatFireworks`, `ChatOpenAICompletions`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (fireworksApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string | accounts/fireworks/models/llama-v3p1-8b-instruct | Model |
| `temperature` | number | 0.9 | Temperature |
| `streaming` | boolean | True | Streaming |

---

### ChatGoogleGenerativeAI (`chatGoogleGenerativeAI`)

**Version:** 3.1  
**Description:** Wrapper around Google Gemini large language models that use the Chat endpoint  
**Base Classes:** `ChatGoogleGenerativeAI`, `LangchainChatGoogleGenerativeAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (googleGenerativeAI)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | gemini-1.5-flash-latest | Model Name |
| `temperature` | number | 0.9 | Temperature |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `customModelName` | string |  | Custom model name to use. If provided, it will override the model selected |
| `streaming` | boolean | True | Streaming |
| `maxOutputTokens` | number |  | Max Output Tokens |
| `topP` | number |  | Top Probability |
| `topK` | number |  | Decode using top-k sampling: consider the set of top_k most probable tokens. Must be positive |
| `safetySettings` | array |  | Safety settings for the model. Refer to the <a href="https://ai.google.dev/gemini-api/docs/safety-se |
| `thinkingBudget` | number |  | Guides the number of thinking tokens. -1 for dynamic, 0 to disable, or positive integer (Gemini 2.5  |
| `baseUrl` | string |  | Base URL for the API. Leave empty to use the default. |

</details>

---

### ChatGoogleVertexAI (`chatGoogleVertexAI`)

**Version:** 5.3  
**Description:** Wrapper around VertexAI large language models that use the Chat endpoint  
**Base Classes:** `ChatGoogleVertexAI`, `ChatVertexAI`, `ChatGoogle`, `ChatGoogleBase`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (googleVertexAuth)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `region` | asyncOptions |  | Region to use for the model. |
| `modelName` | asyncOptions |  | Model Name |
| `temperature` | number | 0.9 | Temperature |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `customModelName` | string |  | Custom model name to use. If provided, it will override the model selected |
| `streaming` | boolean | True | Streaming |
| `maxOutputTokens` | number |  | Max Output Tokens |
| `topP` | number |  | Top Probability |
| `topK` | number |  | Decode using top-k sampling: consider the set of top_k most probable tokens. Must be positive |
| `thinkingBudget` | number |  | Number of tokens to use for thinking process (0 to disable) |

</details>

---

### ChatGroq (`chatGroq_LlamaIndex`)

**Version:** 1  
**Description:** Wrapper around Groq LLM specific for LlamaIndex  
**Base Classes:** `ChatGroq`, `BaseChatModel_LlamaIndex`, `OpenAI`, `ToolCallLLM`, `BaseLLM`  

**Credential Required:** Connect Credential (groqApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions |  | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Max Tokens |

</details>

---

### ChatHuggingFace (`chatHuggingFace`)

**Version:** 3  
**Description:** Wrapper around HuggingFace large language models  
**Base Classes:** `ChatHuggingFace`, `BaseChatModel`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (huggingFaceApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `model` | string |  | Model name (e.g., deepseek-ai/DeepSeek-V3.2-Exp:novita). If model includes provider (:) or using rou |
| `endpoint` | string |  | Custom inference endpoint (optional). Not needed for models with providers (:) or router endpoints.  |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `temperature` | number |  | Temperature parameter may not apply to certain model. Please check available model parameters |
| `maxTokens` | number |  | Max Tokens parameter may not apply to certain model. Please check available model parameters |
| `topP` | number |  | Top Probability parameter may not apply to certain model. Please check available model parameters |
| `hfTopK` | number |  | Top K parameter may not apply to certain model. Please check available model parameters |
| `frequencyPenalty` | number |  | Frequency Penalty parameter may not apply to certain model. Please check available model parameters |
| `stop` | string |  | Sets the stop sequences to use. Use comma to separate different sequences. |

</details>

---

### ChatIBMWatsonx (`chatIBMWatsonx`)

**Version:** 2  
**Description:** Wrapper around IBM watsonx.ai foundation models  
**Base Classes:** `ChatIBMWatsonx`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (ibmWatsonx)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Model |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `frequencyPenalty` | number |  | Positive values penalize new tokens based on their existing frequency in the text so far, decreasing |
| `logprobs` | boolean | False | Whether to return log probabilities of the output tokens or not. If true, returns the log probabilit |
| `n` | number | 1 | How many chat completion choices to generate for each input message. Note that you will be charged b |
| `presencePenalty` | number | 1 | Positive values penalize new tokens based on whether they appear in the text so far, increasing the  |
| `topP` | number | 0.1 | An alternative to sampling with temperature, called nucleus sampling, where the model considers the  |

</details>

---

### ChatLitellm (`chatLitellm`)

**Version:** 2  
**Description:** Connect to a Litellm server using OpenAI-compatible API  
**Base Classes:** `ChatLitellm`, `BaseChatModel`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (litellmApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `imageResolution` | options | low | This parameter controls the resolution in which the model views the image. |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `basePath` | string |  | Base URL |
| `modelName` | string |  | Model Name |
| `temperature` | number | 0.9 | Temperature |
| `allowImageUploads` | boolean | False | Allow image input. Image uploads need a model marked supports_vision=true in LiteLLM. Refer to the < |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top P |
| `timeout` | number |  | Timeout |

</details>

---

### ChatLocalAI (`chatLocalAI`)

**Version:** 3  
**Description:** Use local LLMs like llama.cpp, gpt4all using LocalAI  
**Base Classes:** `ChatLocalAI`, `BaseChatModel`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (localAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `basePath` | string |  | Base Path |
| `modelName` | string |  | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `timeout` | number |  | Timeout |

</details>

---

### ChatMistralAI (`chatMistralAI`)

**Version:** 4  
**Description:** Wrapper around Mistral large language models that use the Chat endpoint  
**Base Classes:** `ChatMistralAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (mistralAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | mistral-tiny | Model Name |
| `temperature` | number | 0.9 | What sampling temperature to use, between 0.0 and 1.0. Higher values like 0.8 will make the output m |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxOutputTokens` | number |  | The maximum number of tokens to generate in the completion. |
| `topP` | number |  | Nucleus sampling, where the model considers the results of the tokens with top_p probability mass. S |
| `randomSeed` | number |  | The seed to use for random sampling. If set, different calls will generate deterministic results. |
| `safeMode` | boolean |  | Whether to inject a safety prompt before all conversations. |
| `overrideEndpoint` | string |  | Override Endpoint |

</details>

---

### ChatMistral (`chatMistral_LlamaIndex`)

**Version:** 1  
**Description:** Wrapper around ChatMistral LLM specific for LlamaIndex  
**Base Classes:** `ChatMistral`, `BaseChatModel_LlamaIndex`, `BaseLLM`  

**Credential Required:** Connect Credential (mistralAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | mistral-tiny | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokensToSample` | number |  | Max Tokens |
| `topP` | number |  | Top P |

</details>

---

### Chat Nemo Guardrails (`chatNemoGuardrails`)

**Version:** 1  
**Description:** Access models through the Nemo Guardrails API  
**Base Classes:** `ChatNemoGuardrails`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `configurationId` | string |  | Configuration ID |
| `baseUrl` | string |  | Base URL |

---

### Chat NVIDIA NIM (`chatNvidiaNIM`)

**Version:** 1.1  
**Description:** Wrapper around NVIDIA NIM Inference API  
**Base Classes:** `ChatNvidiaNIM`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (nvidiaNIMApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Model Name |
| `basePath` | string |  | Specify the URL of the deployed NIM Inference API |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `timeout` | number |  | Timeout |
| `baseOptions` | json |  | Base Options |

</details>

---

### ChatOllama (`chatOllama`)

**Version:** 5  
**Description:** Chat completion using open-source LLM on Ollama  
**Base Classes:** `ChatOllama`, `ChatOllama`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (ollamaApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `baseUrl` | string | http://localhost:11434 | Base URL |
| `modelName` | string |  | Model Name |
| `temperature` | number | 0.9 | The temperature of the model. Increasing the temperature will make the model answer more creatively. |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (15 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `jsonMode` | boolean |  | Coerces model outputs to only return JSON. Specify in the system prompt to return JSON. Ex: Format a |
| `keepAlive` | string | 5m | How long to keep connection alive. A duration string (such as "10m" or "24h") |
| `topP` | number |  | Works together with top-k. A higher value (e.g., 0.95) will lead to more diverse text, while a lower |
| `topK` | number |  | Reduces the probability of generating nonsense. A higher value (e.g. 100) will give more diverse ans |
| `mirostat` | number |  | Enable Mirostat sampling for controlling perplexity. (default: 0, 0 = disabled, 1 = Mirostat, 2 = Mi |
| `mirostatEta` | number |  | Influences how quickly the algorithm responds to feedback from the generated text. A lower learning  |
| `mirostatTau` | number |  | Controls the balance between coherence and diversity of the output. A lower value will result in mor |
| `numCtx` | number |  | Sets the size of the context window used to generate the next token. (Default: 2048) Refer to <a tar |
| `numGpu` | number |  | The number of layers to send to the GPU(s). On macOS it defaults to 1 to enable metal support, 0 to  |
| `numThread` | number |  | Sets the number of threads to use during computation. By default, Ollama will detect this for optima |
| `repeatLastN` | number |  | Sets how far back for the model to look back to prevent repetition. (Default: 64, 0 = disabled, -1 = |
| `repeatPenalty` | number |  | Sets how strongly to penalize repetitions. A higher value (e.g., 1.5) will penalize repetitions more |
| `stop` | string |  | Sets the stop sequences to use. Use comma to seperate different sequences. Refer to <a target="_blan |
| `tfsZ` | number |  | Tail free sampling is used to reduce the impact of less probable tokens from the output. A higher va |

</details>

---

### ChatOllama (`chatOllama_LlamaIndex`)

**Version:** 1  
**Description:** Wrapper around ChatOllama LLM specific for LlamaIndex  
**Base Classes:** `ChatOllama`, `BaseChatModel_LlamaIndex`, `BaseEmbedding`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseUrl` | string | http://localhost:11434 | Base URL |
| `modelName` | string |  | Model Name |
| `temperature` | number | 0.9 | The temperature of the model. Increasing the temperature will make the model answer more creatively. |

<details>
<summary><b>Additional Parameters</b> (12 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topP` | number |  | Works together with top-k. A higher value (e.g., 0.95) will lead to more diverse text, while a lower |
| `topK` | number |  | Reduces the probability of generating nonsense. A higher value (e.g. 100) will give more diverse ans |
| `mirostat` | number |  | Enable Mirostat sampling for controlling perplexity. (default: 0, 0 = disabled, 1 = Mirostat, 2 = Mi |
| `mirostatEta` | number |  | Influences how quickly the algorithm responds to feedback from the generated text. A lower learning  |
| `mirostatTau` | number |  | Controls the balance between coherence and diversity of the output. A lower value will result in mor |
| `numCtx` | number |  | Sets the size of the context window used to generate the next token. (Default: 2048) Refer to <a tar |
| `numGpu` | number |  | The number of layers to send to the GPU(s). On macOS it defaults to 1 to enable metal support, 0 to  |
| `numThread` | number |  | Sets the number of threads to use during computation. By default, Ollama will detect this for optima |
| `repeatLastN` | number |  | Sets how far back for the model to look back to prevent repetition. (Default: 64, 0 = disabled, -1 = |
| `repeatPenalty` | number |  | Sets how strongly to penalize repetitions. A higher value (e.g., 1.5) will penalize repetitions more |
| `stop` | string |  | Sets the stop sequences to use. Use comma to seperate different sequences. Refer to <a target="_blan |
| `tfsZ` | number |  | Tail free sampling is used to reduce the impact of less probable tokens from the output. A higher va |

</details>

---

### ChatOpenAI (`chatOpenAI`)

**Version:** 8.3  
**Description:** Wrapper around OpenAI large language models that use the Chat endpoint  
**Base Classes:** `ChatOpenAI`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (openAIApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `imageResolution` | options | low | This parameter controls the resolution in which the model views the image. |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | gpt-4o-mini | Model Name |
| `temperature` | number | 0.9 | Temperature |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (14 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `timeout` | number |  | Timeout |
| `strictToolCalling` | boolean |  | Whether the model supports the `strict` argument when passing in tools. If not specified, the `stric |
| `stopSequence` | string |  | List of stop words to use when generating. Use comma to separate multiple stop words. |
| `basepath` | string |  | BasePath |
| `proxyUrl` | string |  | Proxy Url |
| `baseOptions` | json |  | BaseOptions |
| `reasoning` | boolean | False | Whether the model supports reasoning. Only applicable for reasoning models. |
| `reasoningEffort` | options |  | Constrains effort on reasoning for reasoning models |
| `reasoningSummary` | options |  | A summary of the reasoning performed by the model. This can be useful for debugging and understandin |

</details>

---

### ChatOpenAI Custom (`chatOpenAICustom`)

**Version:** 4  
**Description:** Custom/FineTuned model using OpenAI Chat compatible API  
**Base Classes:** `ChatOpenAI-Custom`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (openAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |
| `baseOptions` | json |  | BaseOptions |

</details>

---

### ChatOpenAI (`chatOpenAI_LlamaIndex`)

**Version:** 2  
**Description:** Wrapper around OpenAI Chat LLM specific for LlamaIndex  
**Base Classes:** `ChatOpenAI`, `BaseChatModel_LlamaIndex`, `ToolCallLLM`, `BaseLLM`  

**Credential Required:** Connect Credential (openAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | gpt-3.5-turbo | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |

</details>

---

### ChatOpenRouter (`chatOpenRouter`)

**Version:** 1  
**Description:** Wrapper around Open Router Inference API  
**Base Classes:** `ChatOpenRouter`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (openRouterApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `imageResolution` | options | low | This parameter controls the resolution in which the model views the image. |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Model Name |
| `temperature` | number | 0.9 | Temperature |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `timeout` | number |  | Timeout |
| `basepath` | string | https://openrouter.ai/api/v1 | BasePath |
| `baseOptions` | json |  | BaseOptions |

</details>

---

### ChatPerplexity (`chatPerplexity`)

**Version:** 0.1  
**Description:** Wrapper around Perplexity large language models that use the Chat endpoint  
**Base Classes:** `ChatPerplexity`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (perplexityApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `model` | asyncOptions | sonar | Model Name |
| `temperature` | number | 1 | Temperature |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top P |
| `topK` | number |  | Top K |
| `presencePenalty` | number |  | Presence Penalty |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `streaming` | boolean | True | Streaming |
| `timeout` | number |  | Timeout |
| `proxyUrl` | string |  | Proxy Url |

</details>

---

### ChatSambanova (`chatSambanova`)

**Version:** 1  
**Description:** Wrapper around Sambanova Chat Endpoints  
**Base Classes:** `ChatSambanova`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (sambanovaApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string | Meta-Llama-3.3-70B-Instruct | Model |
| `temperature` | number | 0.9 | Temperature |
| `streaming` | boolean | True | Streaming |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `basepath` | string | htps://api.sambanova.ai/v1 | BasePath |
| `baseOptions` | json |  | BaseOptions |

</details>

---

### ChatTogetherAI (`chatTogetherAI`)

**Version:** 2  
**Description:** Wrapper around TogetherAI large language models  
**Base Classes:** `ChatTogetherAI`, `ChatOpenAICompletions`, `BaseChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (togetherAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Refer to <a target="_blank" href="https://docs.together.ai/docs/inference-models">models</a> page |
| `temperature` | number | 0.9 | Temperature |
| `streaming` | boolean | True | Streaming |

---

### ChatTogetherAI (`chatTogetherAI_LlamaIndex`)

**Version:** 1  
**Description:** Wrapper around ChatTogetherAI LLM specific for LlamaIndex  
**Base Classes:** `ChatTogetherAI`, `BaseChatModel_LlamaIndex`, `OpenAI`, `ToolCallLLM`, `BaseLLM`  

**Credential Required:** Connect Credential (togetherAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | string |  | Refer to <a target="_blank" href="https://docs.together.ai/docs/inference-models">models</a> page |
| `temperature` | number | 0.9 | Temperature |

---

### ChatXAI (`chatXAI`)

**Version:** 2  
**Description:** Wrapper around Grok from XAI  
**Base Classes:** `ChatXAI`, `ChatXAI`, `ChatOpenAI`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (xaiApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Model |
| `temperature` | number | 0.9 | Temperature |
| `allowImageUploads` | boolean | False | Allow image input. Refer to the <a href="https://docs.flowiseai.com/using-flowise/uploads#image" tar |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `streaming` | boolean | True | Streaming |
| `maxTokens` | number |  | Max Tokens |
| `maxTokens` | number |  | Max Tokens |

</details>

---

### [Experimental] CIS (Chat) (`cisChat`)

**Version:** 1  
**Description:** Chat with CIS inference endpoint (Gemini-compatible response mapping)  
**Base Classes:** `CISChat`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `endpoint` | string |  | Endpoint URL |
| `featureKey` | string |  | Wd-PCA-Feature-Key header value (e.g., tiare.balbi,<ACTIVE_DIRECTORY_NAME>) |
| `model` | string | gemini-1.5-pro-002 | Model Name |
| `temperature` | number | 0 | Temperature |
| `systemPrompt` | string |  | System Prompt |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `additionalHeaders` | string |  | Additional headers in "key1=value1,key2=value2" format |
| `topP` | number | 0.98 | Top P |
| `topK` | number | 40 | Top K |
| `maxOutputTokens` | number | 4096 | Max Output Tokens |
| `candidateCount` | number | 1 | Candidate Count |
| `provider` | string | gcp | Provider |
| `predictionType` | string | gcp-multimodal-v1 | Prediction Type |

</details>

---

### GroqChat (`groqChat`)

**Version:** 4  
**Description:** Wrapper around Groq API with LPU Inference Engine  
**Base Classes:** `GroqChat`, `BaseChatModel`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (groqApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions |  | Model Name |
| `temperature` | number | 0.9 | Temperature |
| `streaming` | boolean | True | Streaming |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Max Tokens |

</details>

---

## Document Loaders (41)

### S3 (`S3`)

**Version:** 5  
**Description:** Load Data from S3 Buckets  
**Base Classes:** `Document`  

**Credential Required:** AWS Credential (awsApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `unstructuredAPIUrl` | string |  | Your Unstructured.io URL. Read <a target="_blank" href="https://unstructured-io.github.io/unstructur |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `bucketName` | string |  | Bucket |
| `keyName` | string |  | The object key (or key name) that uniquely identifies object in an Amazon S3 bucket |
| `region` | asyncOptions | us-east-1 | Region |
| `fileProcessingMethod` | options | builtIn | File Processing Method |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (20 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |
| `unstructuredAPIUrl` | string |  | Your Unstructured.io URL. Read <a target="_blank" href="https://unstructured-io.github.io/unstructur |
| `unstructuredAPIKey` | password |  | Unstructured API KEY |
| `strategy` | options | auto | The strategy to use for partitioning PDF/image. Options are fast, hi_res, auto. Default: auto. |
| `encoding` | string | utf-8 | The encoding method used to decode the text input. Default: utf-8. |
| `skipInferTableTypes` | multiOptions | ["pdf", "jpg", "png"] | The document types that you want to skip table extraction with. Default: pdf, jpg, png. |
| `hiResModelName` | options | detectron2_onnx | The name of the inference model used when strategy is hi_res. Default: detectron2_onnx. |
| `chunkingStrategy` | options | by_title | Use one of the supported strategies to chunk the returned elements. When omitted, no chunking is per |
| `ocrLanguages` | multiOptions |  | The languages to use for OCR. Note: Being depricated as languages is the new type. Pending langchain |
| `sourceIdKey` | string | source | Key used to get the true source of document, to be compared against the record. Document metadata mu |
| `coordinates` | boolean | False | If true, return coordinates for each element. Default: false. |
| `xmlKeepTags` | boolean |  | If True, will retain the XML tags in the output. Otherwise it will simply extract the text from with |
| `includePageBreaks` | boolean |  | When true, the output will include page break elements when the filetype supports it. |
| `multiPageSections` | boolean |  | Whether to treat multi-page documents as separate sections. |
| `combineUnderNChars` | number |  | If chunking strategy is set, combine elements until a section reaches a length of n chars. Default:  |
| `newAfterNChars` | number |  | If chunking strategy is set, cut off new sections after reaching a length of n chars (soft max). val |
| `maxCharacters` | number | 500 | If chunking strategy is set, cut off new sections after reaching a length of n chars (hard max). Def |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Airtable (`airtable`)

**Version:** 3.02  
**Description:** Load data from Airtable table  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (airtableApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `baseId` | string |  | If your table URL looks like: https://airtable.com/app11RobdGoX0YNsC/tblJdmvbrgizbYICO/viw9UrP77Id0C |
| `tableId` | string |  | If your table URL looks like: https://airtable.com/app11RobdGoX0YNsC/tblJdmvbrgizbYICO/viw9UrP77Id0C |
| `viewId` | string |  | If your view URL looks like: https://airtable.com/app11RobdGoX0YNsC/tblJdmvbrgizbYICO/viw9UrP77Id0CE |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `fields` | string |  | Comma-separated list of field names or IDs to include. If empty, then ALL fields are used. Use field |
| `returnAll` | boolean | True | If all results should be returned or only up to a given limit |
| `limit` | number | 100 | Number of results to return. Ignored when Return All is enabled. |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |
| `filterByFormula` | string |  | A formula used to filter records. The formula will be evaluated for each record, and if the result i |

</details>

---

### API Loader (`apiLoader`)

**Version:** 2.1  
**Description:** Load data from an API  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `method` | options |  | Method |
| `url` | string |  | URL |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `headers` | json |  | Headers |
| `caFile` | file |  | Please upload a SSL certificate file in either .pem or .crt |
| `body` | json |  | JSON body for the POST request. If not specified, agent will try to figure out itself from AIPlugin  |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Apify Website Content Crawler (`apifyWebsiteContentCrawler`)

**Version:** 3  
**Description:** Load data from Apify Website Content Crawler  
**Base Classes:** `Document`  

**Credential Required:** Connect Apify API (apifyApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `urls` | string |  | One or more URLs of pages where the crawler will start, separated by commas. |
| `crawlerType` | options | playwright:firefox | Select the crawling engine, see <a target="_blank" href="https://apify.com/apify/website-content-cra |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxCrawlDepth` | number | 1 | Max crawling depth |
| `maxCrawlPages` | number | 3 | Max crawl pages |
| `additionalInput` | json | {} | For additional input options for the crawler see <a target="_blank" href="https://apify.com/apify/we |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### BraveSearch API Document Loader (`braveSearchApiLoader`)

**Version:** 2  
**Description:** Load and process data from BraveSearch results  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (braveSearchApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `query` | string |  | Query |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Cheerio Web Scraper (`cheerioWebScraper`)

**Version:** 2  
**Description:** Load data from webpages  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | string |  | URL |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `relativeLinksMethod` | options | webCrawl | Select a method to retrieve relative links |
| `limit` | number | 10 | Only used when "Get Relative Links Method" is selected. Set 0 to retrieve all relative links, defaul |
| `selector` | string |  | Specify a CSS selector to select the content to be extracted |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Confluence (`confluence`)

**Version:** 2  
**Description:** Load data from a Confluence Document  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (confluenceCloudApi, confluenceServerDCApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `baseUrl` | string |  | Base URL |
| `spaceKey` | string |  | Refer to <a target="_blank" href="https://community.atlassian.com/t5/Confluence-questions/How-to-fin |
| `limit` | number | 0 | Limit |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Csv File (`csvFile`)

**Version:** 3  
**Description:** Load data from CSV files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `csvFile` | file |  | Csv File |
| `textSplitter` | TextSplitter |  | Text Splitter |
| `columnName` | string |  | Extracting a single column |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Custom Document Loader (`customDocumentLoader`)

**Version:** 1  
**Description:** Custom function for loading documents  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `functionInputVariables` | json |  | Input variables can be used in the function with prefix $. For example: $var |
| `javascriptFunction` | code |  | Must return an array of document objects containing metadata and pageContent if "Document" is select |

---

### Document Store (`documentStore`)

**Version:** 1  
**Description:** Load data from pre-configured document stores  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `selectedStore` | asyncOptions |  | Select Store |

---

### Docx File (`docxFile`)

**Version:** 2  
**Description:** Load data from DOCX files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `docxFile` | file |  | Docx File |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Epub File (`epubFile`)

**Version:** 1  
**Description:** Load data from EPUB files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `epubFile` | file |  | Epub File |
| `textSplitter` | TextSplitter |  | Text Splitter |
| `usage` | options | perChapter | Usage |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Metadata keys to omit, comma-separated |

</details>

---

### Figma (`figma`)

**Version:** 2  
**Description:** Load data from a Figma file  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (figmaApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `fileKey` | string |  | The file key can be read from any Figma file URL: https://www.figma.com/file/:key/:title. For exampl |
| `nodeIds` | string |  | A list of Node IDs, seperated by comma. Refer to <a target="_blank" href="https://www.figma.com/comm |
| `recursive` | boolean |  | Recursive |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### File Loader (`fileLoader`)

**Version:** 2  
**Description:** A generic file loader that can load different file types  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `file` | file |  | File |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `usage` | options | perPage | Only when loading PDF files |
| `legacyBuild` | boolean |  | Use legacy build for PDF compatibility issues |
| `pointerName` | string |  | Only when loading JSONL files |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### FireCrawl (`fireCrawl`)

**Version:** 4  
**Description:** Load data from URL using FireCrawl  
**Base Classes:** `Document`  

**Credential Required:** FireCrawl API (fireCrawlApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `crawlerType` | options | crawl | Type |
| `url` | string |  | URL to be crawled/scraped/extracted |
| `searchQuery` | string |  | Search query to find relevant content |

<details>
<summary><b>Additional Parameters</b> (12 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `includeTags` | string |  | Tags to include in the output. Use comma to separate multiple tags. |
| `excludeTags` | string |  | Tags to exclude from the output. Use comma to separate multiple tags. |
| `onlyMainContent` | boolean |  | Extract only the main content of the page |
| `limit` | string | 10000 | Maximum number of pages to crawl |
| `includePaths` | string |  | URL pathname regex patterns that include matching URLs in the crawl. Only the paths that match the s |
| `excludePaths` | string |  | URL pathname regex patterns that exclude matching URLs from the crawl. |
| `extractSchema` | json |  | JSON schema for data extraction |
| `extractPrompt` | string |  | Prompt for data extraction |
| `searchLimit` | string | 5 | Maximum number of results to return |
| `searchLang` | string | en | Language code for search results (e.g., en, es, fr) |
| `searchCountry` | string | us | Country code for search results (e.g., us, uk, ca) |
| `searchTimeout` | number | 60000 | Timeout in milliseconds for search operation |

</details>

---

### Folder with Files (`folderFiles`)

**Version:** 4  
**Description:** Load data from folder with multiple files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `folderPath` | string |  | Folder Path |
| `recursive` | boolean |  | Recursive |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `pdfUsage` | options | perPage | Only when loading PDF files |
| `pointerName` | string |  | Only when loading JSONL files |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### GitBook (`gitbook`)

**Version:** 2  
**Description:** Load data from GitBook  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `webPath` | string |  | If want to load all paths from the GitBook provide only root path e.g.https://docs.gitbook.com/  |
| `shouldLoadAllPaths` | boolean |  | Load from all paths in a given GitBook |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Github (`github`)

**Version:** 3  
**Description:** Load data from a GitHub repository  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (githubApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `repoLink` | string |  | Repo Link |
| `branch` | string | main | Branch |
| `recursive` | boolean |  | Recursive |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxConcurrency` | number |  | Max Concurrency |
| `githubBaseUrl` | string |  | Custom Github Base Url (e.g. Enterprise) |
| `githubInstanceApi` | string |  | Custom Github API Url (e.g. Enterprise) |
| `ignorePath` | string |  | An array of paths to be ignored |
| `maxRetries` | number |  | The maximum number of retries that can be made for a single call, with an exponential backoff betwee |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Google Drive (`googleDrive`)

**Version:** 1  
**Description:** Load documents from Google Drive files  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (googleDriveOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `selectedFiles` | asyncMultiOptions |  | Select files from your Google Drive |
| `folderId` | string |  | Google Drive folder ID to load all files from (alternative to selecting specific files) |
| `fileTypes` | multiOptions | ['application/vnd.google-apps.document', 'application/vnd.google-apps.spreadsheet', 'application/vnd.google-apps.presentation', 'text/plain', 'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.openxmlformats-officedocument.presentationml.presentation', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'] | Types of files to load |
| `includeSubfolders` | boolean | False | Whether to include files from subfolders when loading from a folder |
| `includeSharedDrives` | boolean | False | Whether to include files from shared drives (Team Drives) that you have access to |
| `maxFiles` | number | 50 | Maximum number of files to load (default: 50) |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Google Sheets (`googleSheets`)

**Version:** 1  
**Description:** Load data from Google Sheets as documents  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (googleSheetsOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `spreadsheetIds` | asyncMultiOptions |  | Select spreadsheet from your Google Drive |
| `sheetNames` | string |  | Comma-separated list of sheet names to load. If empty, loads all sheets. |
| `range` | string |  | Range to load (e.g., A1:E10). If empty, loads entire sheet. |
| `includeHeaders` | boolean | True | Whether to include the first row as headers |
| `valueRenderOption` | options | FORMATTED_VALUE | How values should be represented in the output |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Jira (`jira`)

**Version:** 1  
**Description:** Load issues from Jira  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (jiraApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `host` | string |  | Host |
| `projectKey` | string | main | Project Key |
| `limitPerRequest` | number |  | Limit per request |
| `createdAfter` | string |  | Created after |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Json File (`jsonFile`)

**Version:** 3.1  
**Description:** Load data from JSON files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `jsonFile` | file |  | Json File |
| `textSplitter` | TextSplitter |  | Text Splitter |
| `pointersName` | string |  | Ex: { "key": "value" }, Pointer Extraction = "key", "value" will be extracted as pageContent of the  |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `separateByObject` | boolean |  | If enabled and the file is a JSON Array, each JSON object will be extracted as a chunk |
| `metadata` | json |  | Additional metadata to be added to the extracted documents. You can add metadata dynamically from th |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Json Lines File (`jsonlinesFile`)

**Version:** 3  
**Description:** Load data from JSON Lines files  
**Base Classes:** `Document`  

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `pointerName` | string |  | Ex: { "key": "value" }, Pointer Extraction = "key", "value" will be extracted as pageContent of the  |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `jsonlinesFile` | file |  | Jsonlines File |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents. You can add metadata dynamically from th |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Microsoft Excel (`microsoftExcel`)

**Version:** 1  
**Description:** Load data from Microsoft Excel files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `excelFile` | file |  | Excel File |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Microsoft PowerPoint (`microsoftPowerpoint`)

**Version:** 1  
**Description:** Load data from Microsoft PowerPoint files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `powerpointFile` | file |  | PowerPoint File |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Microsoft Word (`microsoftWord`)

**Version:** 1  
**Description:** Load data from Microsoft Word files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `docxFile` | file |  | Word File |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Notion Database (`notionDB`)

**Version:** 2  
**Description:** Load data from Notion Database (each row is a separate document with all properties as metadata)  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (notionApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `databaseId` | string |  | If your URL looks like - https://www.notion.so/abcdefh?v=long_hash_2, then abcdefh is the database I |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Notion Folder (`notionFolder`)

**Version:** 2  
**Description:** Load data from the exported and unzipped Notion folder  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `notionFolder` | string |  | Get folder path |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Notion Page (`notionPage`)

**Version:** 2  
**Description:** Load data from Notion Page (including child pages all as separate documents)  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (notionApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `pageId` | string |  | The last The 32 char hex in the url path. For example: https://www.notion.so/skarard/LangChain-Notio |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Oxylabs (`oxylabs`)

**Version:** 1  
**Description:** Extract data from URLs using Oxylabs  
**Base Classes:** `Document`  

**Credential Required:** Oxylabs API (oxylabsApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `query` | string |  | Website URL of query keyword. |
| `source` | options | universal | Target website to scrape. |
| `geo_location` | string |  | Sets the proxy's geo location to retrieve data. Check Oxylabs documentation for more details. |
| `render` | boolean | False | Enables JavaScript rendering when set to true. |
| `parse` | boolean | False | Returns parsed data when set to true, as long as a dedicated parser exists for the submitted URL's p |
| `user_agent_type` | options |  | Device type and browser. |

---

### Pdf File (`pdfFile`)

**Version:** 2  
**Description:** Load data from PDF files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `pdfFile` | file |  | Pdf File |
| `textSplitter` | TextSplitter |  | Text Splitter |
| `usage` | options | perPage | Usage |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `legacyBuild` | boolean |  | Use Legacy Build |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Plain Text (`plainText`)

**Version:** 2  
**Description:** Load data from plain text  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `text` | string |  | Text |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Playwright Web Scraper (`playwrightWebScraper`)

**Version:** 2  
**Description:** Load data from webpages  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | string |  | URL |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `relativeLinksMethod` | options | webCrawl | Select a method to retrieve relative links |
| `limit` | number | 10 | Only used when "Get Relative Links Method" is selected. Set 0 to retrieve all relative links, defaul |
| `waitUntilGoToOption` | options |  | Select a go to wait until option |
| `waitForSelector` | string |  | CSS selectors like .div or #div |
| `cssSelector` | string |  | Only content inside this selector will be extracted. Leave empty to use the entire page body. |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Puppeteer Web Scraper (`puppeteerWebScraper`)

**Version:** 2  
**Description:** Load data from webpages  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | string |  | URL |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `relativeLinksMethod` | options | webCrawl | Select a method to retrieve relative links |
| `limit` | number | 10 | Only used when "Get Relative Links Method" is selected. Set 0 to retrieve all relative links, defaul |
| `waitUntilGoToOption` | options |  | Select a go to wait until option |
| `waitForSelector` | string |  | CSS selectors like .div or #div |
| `cssSelector` | string |  | Only content inside this selector will be extracted. Leave empty to use the entire page body. |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### S3 Directory (`s3Directory`)

**Version:** 4  
**Description:** Load Data from S3 Buckets  
**Base Classes:** `Document`  

**Credential Required:** Credential (awsApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `bucketName` | string |  | Bucket |
| `region` | asyncOptions | us-east-1 | Region |
| `serverUrl` | string |  | The fully qualified endpoint of the webservice. This is only for using a custom endpoint (for exampl |
| `prefix` | string |  | Limits the response to keys that begin with the specified prefix |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `pdfUsage` | options | perPage | Pdf Usage |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### SearchApi For Web Search (`searchApi`)

**Version:** 2  
**Description:** Load data from real-time search results  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (searchApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `query` | string |  | Query |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `customParameters` | json |  | Custom Parameters |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### SerpApi For Web Search (`serpApi`)

**Version:** 2  
**Description:** Load and process data from web search results  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (serpApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `query` | string |  | Query |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Spider Document Loaders (`spiderDocumentLoaders`)

**Version:** 2  
**Description:** Scrape & Crawl the web with Spider  
**Base Classes:** `Document`  

**Credential Required:** Credential (spiderApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `textSplitter` | TextSplitter |  | Text Splitter |
| `mode` | options | scrape | Mode |
| `url` | string |  | Web Page URL |
| `limit` | number | 25 | Limit |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `additional_metadata` | json |  | Additional metadata to be added to the extracted documents |
| `params` | json |  | Find all the available parameters in the <a _target="blank" href="https://spider.cloud/docs/api">Spi |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Text File (`textFile`)

**Version:** 3  
**Description:** Load data from text files  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `txtFile` | file |  | Txt File |
| `textSplitter` | TextSplitter |  | Text Splitter |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### Unstructured File Loader (`unstructuredFileLoader`)

**Version:** 4  
**Description:** Use Unstructured.io to load data from a file path  
**Base Classes:** `Document`  

**Credential Required:** Connect Credential (unstructuredApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `unstructuredAPIUrl` | string |  | Unstructured API URL. Read <a target="_blank" href="https://docs.unstructured.io/api-reference/api-s |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `fileObject` | file |  | Files to be processed. Multiple files can be uploaded. |

<details>
<summary><b>Additional Parameters</b> (17 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `strategy` | options | auto | The strategy to use for partitioning PDF/image. Options are fast, hi_res, auto. Default: auto. |
| `encoding` | string | utf-8 | The encoding method used to decode the text input. Default: utf-8. |
| `skipInferTableTypes` | multiOptions | ["pdf", "jpg", "png"] | The document types that you want to skip table extraction with. Default: pdf, jpg, png. |
| `hiResModelName` | options |  | The name of the inference model used when strategy is hi_res |
| `chunkingStrategy` | options | by_title | Use one of the supported strategies to chunk the returned elements. When omitted, no chunking is per |
| `ocrLanguages` | multiOptions |  | The languages to use for OCR. Note: Being depricated as languages is the new type. Pending langchain |
| `sourceIdKey` | string | source | Key used to get the true source of document, to be compared against the record. Document metadata mu |
| `coordinates` | boolean | False | If true, return coordinates for each element. Default: false. |
| `xmlKeepTags` | boolean |  | If True, will retain the XML tags in the output. Otherwise it will simply extract the text from with |
| `includePageBreaks` | boolean |  | When true, the output will include page break elements when the filetype supports it. |
| `xmlKeepTags` | boolean |  | Whether to keep XML tags in the output. |
| `multiPageSections` | boolean |  | Whether to treat multi-page documents as separate sections. |
| `combineUnderNChars` | number |  | If chunking strategy is set, combine elements until a section reaches a length of n chars. Default:  |
| `newAfterNChars` | number |  | If chunking strategy is set, cut off new sections after reaching a length of n chars (soft max). val |
| `maxCharacters` | number | 500 | If chunking strategy is set, cut off new sections after reaching a length of n chars (hard max). Def |
| `metadata` | json |  | Additional metadata to be added to the extracted documents |
| `omitMetadataKeys` | string |  | Each document loader comes with a default set of metadata keys that are extracted from the document. |

</details>

---

### VectorStore To Document (`vectorStoreToDocument`)

**Version:** 2  
**Description:** Search documents with scores from vector store  
**Base Classes:** `Document`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `vectorStore` | VectorStore |  | Vector Store |
| `query` | string |  | Query to retrieve documents from vector database. If not specified, user question will be used |
| `minScore` | number |  | Minumum score for embeddings documents to be included |

---

## Embeddings (17)

### AWS Bedrock Embeddings (`AWSBedrockEmbeddings`)

**Version:** 5  
**Description:** AWSBedrock embedding models to generate embeddings for a given text  
**Base Classes:** `AWSBedrockEmbeddings`, `Embeddings`  

**Credential Required:** AWS Credential (awsApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `region` | asyncOptions | us-east-1 | Region |
| `model` | asyncOptions | amazon.titan-embed-text-v1 | Model Name |
| `customModel` | string |  | If provided, will override model selected from Model Name option |
| `inputType` | options |  | Specifies the type of input passed to the model. Required for cohere embedding models v3 and higher. |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `batchSize` | number | 50 | Documents batch size to send to AWS API for Titan model embeddings. Used to avoid throttling. |
| `maxRetries` | number | 5 | This will limit the number of AWS API for Titan model embeddings call retries. Used to avoid throttl |

</details>

---

### Azure OpenAI Embeddings (`azureOpenAIEmbeddings`)

**Version:** 2  
**Description:** Azure OpenAI API to generate embeddings for a given text  
**Base Classes:** `AzureOpenAIEmbeddings`, `OpenAIEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (azureOpenAIApi)

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `batchSize` | number | 100 | Batch Size |
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |
| `baseOptions` | json |  | BaseOptions |

</details>

---

### Azure OpenAI Embeddings (`azureOpenAIEmbeddingsLlamaIndex`)

**Version:** 1  
**Description:** Azure OpenAI API embeddings specific for LlamaIndex  
**Base Classes:** `AzureOpenAIEmbeddings`, `BaseEmbedding_LlamaIndex`, `BaseEmbedding`  

**Credential Required:** Connect Credential (azureOpenAIApi)

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `timeout` | number |  | Timeout |

</details>

---

### Cohere Embeddings (`cohereEmbeddings`)

**Version:** 3  
**Description:** Cohere API to generate embeddings for a given text  
**Base Classes:** `CohereEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (cohereApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | embed-english-v2.0 | Model Name |
| `inputType` | options | search_query | Specifies the type of input passed to the model. Required for embedding models v3 and higher. <a tar |

---

### GoogleGenerativeAI Embeddings (`googleGenerativeAiEmbeddings`)

**Version:** 2  
**Description:** Google Generative API to generate embeddings for a given text  
**Base Classes:** `GoogleGenerativeAiEmbeddings`, `GoogleGenerativeAIEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (googleGenerativeAI)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | embedding-001 | Model Name |
| `tasktype` | options | TASK_TYPE_UNSPECIFIED | Type of task for which the embedding will be used |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `stripNewLines` | boolean |  | Remove new lines from input text before embedding to reduce token count |

</details>

---

### GoogleVertexAI Embeddings (`googlevertexaiEmbeddings`)

**Version:** 2.1  
**Description:** Google vertexAI API to generate embeddings for a given text  
**Base Classes:** `GoogleVertexAIEmbeddings`, `VertexAIEmbeddings`, `GoogleEmbeddings`, `BaseGoogleEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (googleVertexAuth)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | text-embedding-004 | Model Name |
| `region` | asyncOptions |  | Region to use for the model. |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `stripNewLines` | boolean |  | Remove new lines from input text before embedding to reduce token count |

</details>

---

### HuggingFace Inference Embeddings (`huggingFaceInferenceEmbeddings`)

**Version:** 1  
**Description:** HuggingFace Inference API to generate embeddings for a given text  
**Base Classes:** `HuggingFaceInferenceEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (huggingFaceApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | string |  | If using own inference endpoint, leave this blank |
| `endpoint` | string |  | Using your own inference endpoint |

---

### IBM Watsonx Embeddings (`ibmEmbedding`)

**Version:** 1  
**Description:** Generate embeddings for a given text using open source model on IBM Watsonx  
**Base Classes:** `WatsonxEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (ibmWatsonx)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | string | ibm/slate-30m-english-rtrvr | Model Name |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `truncateInputTokens` | number |  | Truncate the input tokens. |
| `maxRetries` | number |  | The maximum number of retries. |
| `maxConcurrency` | number |  | The maximum number of concurrencies. |

</details>

---

### Jina Embeddings (`jinaEmbeddings`)

**Version:** 3  
**Description:** JinaAI API to generate embeddings for a given text  
**Base Classes:** `JinaEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (jinaAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | string | jina-embeddings-v3 | Refer to <a href="https://jina.ai/embeddings/" target="_blank">JinaAI documentation</a> for availabl |
| `modelDimensions` | number | 1024 | Refer to <a href="https://jina.ai/embeddings/" target="_blank">JinaAI documentation</a> for availabl |
| `allowLateChunking` | boolean | False | Refer to <a href="https://jina.ai/embeddings/" target="_blank">JinaAI documentation</a> guidance on  |

---

### LocalAI Embeddings (`localAIEmbeddings`)

**Version:** 1  
**Description:** Use local embeddings models like llama.cpp  
**Base Classes:** `LocalAI Embeddings`, `Embeddings`  

**Credential Required:** Connect Credential (localAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `basePath` | string |  | Base Path |
| `modelName` | string |  | Model Name |

---

### MistralAI Embeddings (`mistralAIEmbeddings`)

**Version:** 2  
**Description:** MistralAI API to generate embeddings for a given text  
**Base Classes:** `MistralAIEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (mistralAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | mistral-embed | Model Name |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `batchSize` | number | 512 | Batch Size |
| `stripNewLines` | boolean | True | Strip New Lines |
| `overrideEndpoint` | string |  | Override Endpoint |

</details>

---

### Ollama Embeddings (`ollamaEmbedding`)

**Version:** 2  
**Description:** Generate embeddings for a given text using open source model on Ollama  
**Base Classes:** `OllamaEmbeddings`, `Embeddings`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseUrl` | string | http://localhost:11434 | Base URL |
| `modelName` | string |  | Model Name |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `numGpu` | number |  | The number of layers to send to the GPU(s). On macOS it defaults to 1 to enable metal support, 0 to  |
| `numThread` | number |  | Sets the number of threads to use during computation. By default, Ollama will detect this for optima |
| `useMMap` | boolean | True | Use MMap |

</details>

---

### OpenAI Embedding (`openAIEmbedding_LlamaIndex`)

**Version:** 2  
**Description:** OpenAI Embedding specific for LlamaIndex  
**Base Classes:** `OpenAIEmbedding`, `BaseEmbedding_LlamaIndex`, `BaseEmbedding`  

**Credential Required:** Connect Credential (openAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | text-embedding-ada-002 | Model Name |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |

</details>

---

### OpenAI Embeddings (`openAIEmbeddings`)

**Version:** 4  
**Description:** OpenAI API to generate embeddings for a given text  
**Base Classes:** `OpenAIEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (openAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | text-embedding-ada-002 | Model Name |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `stripNewLines` | boolean |  | Strip New Lines |
| `batchSize` | number |  | Batch Size |
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |
| `dimensions` | number |  | Dimensions |

</details>

---

### OpenAI Embeddings Custom (`openAIEmbeddingsCustom`)

**Version:** 3  
**Description:** OpenAI API to generate embeddings for a given text  
**Base Classes:** `OpenAIEmbeddingsCustom`, `Embeddings`  

**Credential Required:** Connect Credential (openAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | string |  | Model Name |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `stripNewLines` | boolean |  | Strip New Lines |
| `batchSize` | number |  | Batch Size |
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |
| `baseOptions` | json |  | BaseOptions |
| `dimensions` | number |  | Dimensions |

</details>

---

### TogetherAIEmbedding (`togetherAIEmbedding`)

**Version:** 1  
**Description:** TogetherAI Embedding models to generate embeddings for a given text  
**Base Classes:** `TogetherAIEmbedding`, `Embeddings`  

**Credential Required:** Connect Credential (togetherAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | Refer to <a target="_blank" href="https://docs.together.ai/docs/embedding-models">embedding models</ |

---

### VoyageAI Embeddings (`voyageAIEmbeddings`)

**Version:** 2  
**Description:** Voyage AI API to generate embeddings for a given text  
**Base Classes:** `VoyageAIEmbeddings`, `Embeddings`  

**Credential Required:** Connect Credential (voyageAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `modelName` | asyncOptions | voyage-2 | Model Name |

---

## Engine (4)

### Context Chat Engine (`contextChatEngine`)

**Version:** 1  
**Description:** Answer question based on retrieved documents (context) with built-in memory to remember conversation  
**Base Classes:** `ContextChatEngine`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel_LlamaIndex |  | Chat Model |
| `vectorStoreRetriever` | VectorIndexRetriever |  | Vector Store Retriever |
| `memory` | BaseChatMemory |  | Memory |
| `returnSourceDocuments` | boolean |  | Return Source Documents |
| `systemMessagePrompt` | string |  | System Message |

---

### Query Engine (`queryEngine`)

**Version:** 2  
**Description:** Simple query engine built to answer question over your data, without memory  
**Base Classes:** `QueryEngine`, `BaseQueryEngine`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `vectorStoreRetriever` | VectorIndexRetriever |  | Vector Store Retriever |
| `responseSynthesizer` | ResponseSynthesizer |  | ResponseSynthesizer is responsible for sending the query, nodes, and prompt templates to the LLM to  |
| `returnSourceDocuments` | boolean |  | Return Source Documents |

---

### Simple Chat Engine (`simpleChatEngine`)

**Version:** 1  
**Description:** Simple engine to handle back and forth conversations  
**Base Classes:** `SimpleChatEngine`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel_LlamaIndex |  | Chat Model |
| `memory` | BaseChatMemory |  | Memory |
| `systemMessagePrompt` | string |  | System Message |

---

### Sub Question Query Engine (`subQuestionQueryEngine`)

**Version:** 2  
**Description:** Breaks complex query into sub questions for each relevant data source, then gather all the intermediate responses and synthesizes a final response  
**Base Classes:** `SubQuestionQueryEngine`, `BaseQueryEngine`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `queryEngineTools` | QueryEngineTool |  | QueryEngine Tools |
| `model` | BaseChatModel_LlamaIndex |  | Chat Model |
| `embeddings` | BaseEmbedding_LlamaIndex |  | Embeddings |
| `responseSynthesizer` | ResponseSynthesizer |  | ResponseSynthesizer is responsible for sending the query, nodes, and prompt templates to the LLM to  |
| `returnSourceDocuments` | boolean |  | Return Source Documents |

---

## Graph (1)

### Neo4j (`Neo4j`)

**Version:** 1  
**Description:** Connect with Neo4j graph database  
**Base Classes:** `Neo4j`  

**Credential Required:** Connect Credential (neo4jApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `database` | string |  | Database |
| `timeoutMs` | number | 5000 | Timeout (ms) |
| `enhancedSchema` | boolean | False | Enhanced Schema |

---

## LLMs (13)

### AWS Bedrock (`awsBedrock`)

**Version:** 4  
**Description:** Wrapper around AWS Bedrock large language models  
**Base Classes:** `AWSBedrock`, `Bedrock`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** AWS Credential (awsApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `region` | asyncOptions | us-east-1 | Region |
| `model` | asyncOptions |  | Model Name |
| `customModel` | string |  | If provided, will override model selected from Model Name option |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `temperature` | number | 0.7 | Temperature parameter may not apply to certain model. Please check available model parameters |
| `max_tokens_to_sample` | number | 200 | Max Tokens parameter may not apply to certain model. Please check available model parameters |

</details>

---

### Azure OpenAI (`azureOpenAI`)

**Version:** 4  
**Description:** Wrapper around Azure OpenAI large language models  
**Base Classes:** `AzureOpenAI`, `OpenAI`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (azureOpenAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | text-davinci-003 | Model Name |
| `temperature` | number | 0.9 | Temperature |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `bestOf` | number |  | Best Of |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |

</details>

---

### [Experimental] CIS (`cis`)

**Version:** 1  
**Description:** CIS LLM through CIS inference endpoint (Gemini-compatible response mapping)  
**Base Classes:** `CIS`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `endpoint` | string |  | Endpoint URL |
| `featureKey` | string |  | Wd-PCA-Feature-Key header value (e.g., tiare.balbi,<ACTIVE_DIRECTORY_NAME>) |
| `model` | string | gemini-1.5-pro-002 | Model Name |
| `temperature` | number | 0 | Temperature |
| `systemPrompt` | string |  | System Prompt |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `additionalHeaders` | string |  | Additional headers in "key1=value1,key2=value2" format |
| `topP` | number | 0.98 | Top P |
| `topK` | number | 40 | Top K |
| `maxOutputTokens` | number | 4096 | Max Output Tokens |
| `candidateCount` | number | 1 | Candidate Count |
| `provider` | string | gcp | Provider |
| `predictionType` | string | gcp-multimodal-v1 | Prediction Type |

</details>

---

### Cohere (`cohere`)

**Version:** 3  
**Description:** Wrapper around Cohere large language models  
**Base Classes:** `Cohere`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (cohereApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | command | Model Name |
| `temperature` | number | 0.7 | Temperature |
| `maxTokens` | number |  | Max Tokens |

---

### Fireworks (`fireworks`)

**Version:** 1  
**Description:** Wrapper around Fireworks API for large language models  
**Base Classes:** `Fireworks`, `OpenAI`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (fireworksApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string | accounts/fireworks/models/llama-v3-70b-instruct-hf | For more details see https://fireworks.ai/models |

---

### GoogleVertexAI (`googlevertexai`)

**Version:** 3  
**Description:** Wrapper around GoogleVertexAI large language models  
**Base Classes:** `GoogleVertexAI`, `GoogleLLM`, `GoogleBaseLLM`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (googleVertexAuth)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | text-bison | Model Name |
| `temperature` | number | 0.7 | Temperature |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxOutputTokens` | number |  | max Output Tokens |
| `topP` | number |  | Top Probability |

</details>

---

### HuggingFace Inference (`huggingFaceInference_LLMs`)

**Version:** 2  
**Description:** Wrapper around HuggingFace large language models  
**Base Classes:** `HuggingFaceInference`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (huggingFaceApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `model` | string |  | If using own inference endpoint, leave this blank |
| `endpoint` | string |  | Using your own inference endpoint |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `temperature` | number |  | Temperature parameter may not apply to certain model. Please check available model parameters |
| `maxTokens` | number |  | Max Tokens parameter may not apply to certain model. Please check available model parameters |
| `topP` | number |  | Top Probability parameter may not apply to certain model. Please check available model parameters |
| `hfTopK` | number |  | Top K parameter may not apply to certain model. Please check available model parameters |
| `frequencyPenalty` | number |  | Frequency Penalty parameter may not apply to certain model. Please check available model parameters |

</details>

---

### IBMWatsonx (`ibmWatsonx`)

**Version:** 1  
**Description:** Wrapper around IBM watsonx.ai foundation models  
**Base Classes:** `IBMWatsonx`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (ibmWatsonx)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelId` | string | ibm/granite-13b-instruct-v2 | The name of the model to query. |
| `streaming` | boolean | False | Whether or not to stream tokens as they are generated. |

<details>
<summary><b>Additional Parameters</b> (10 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `decodingMethod` | options | greedy | Set decoding to Greedy to always select words with the highest probability. Set decoding to Sampling |
| `topK` | number | 50 | The topK parameter is used to limit the number of choices for the next predicted word or token. It s |
| `topP` | number | 0.7 | The topP (nucleus) parameter is used to dynamically adjust the number of choices for each predicted  |
| `temperature` | number | 0.7 | A decimal number that determines the degree of randomness in the response. A value of 1 will always  |
| `repetitionPenalty` | number | 1 | A number that controls the diversity of generated text by reducing the likelihood of repeated sequen |
| `maxNewTokens` | number | 100 | The maximum number of new tokens to be generated. The maximum supported value for this field depends |
| `minNewTokens` | number | 1 | If stop sequences are given, they are ignored until minimum tokens are generated. |
| `stopSequence` | string |  | A list of tokens at which the generation should stop. |
| `includeStopSequence` | boolean | False | Pass false to omit matched stop sequences from the end of the output text. The default is true, mean |
| `randomSeed` | number |  | Random number generator seed to use in sampling mode for experimental repeatability. |

</details>

---

### Ollama (`ollama`)

**Version:** 2  
**Description:** Wrapper around open source large language models on Ollama  
**Base Classes:** `Ollama`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `baseUrl` | string | http://localhost:11434 | Base URL |
| `modelName` | string |  | Model Name |
| `temperature` | number | 0.9 | The temperature of the model. Increasing the temperature will make the model answer more creatively. |

<details>
<summary><b>Additional Parameters</b> (13 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topP` | number |  | Works together with top-k. A higher value (e.g., 0.95) will lead to more diverse text, while a lower |
| `topK` | number |  | Reduces the probability of generating nonsense. A higher value (e.g. 100) will give more diverse ans |
| `mirostat` | number |  | Enable Mirostat sampling for controlling perplexity. (default: 0, 0 = disabled, 1 = Mirostat, 2 = Mi |
| `mirostatEta` | number |  | Influences how quickly the algorithm responds to feedback from the generated text. A lower learning  |
| `mirostatTau` | number |  | Controls the balance between coherence and diversity of the output. A lower value will result in mor |
| `numCtx` | number |  | Sets the size of the context window used to generate the next token. (Default: 2048) Refer to <a tar |
| `numGqa` | number |  | The number of GQA groups in the transformer layer. Required for some models, for example it is 8 for |
| `numGpu` | number |  | The number of layers to send to the GPU(s). On macOS it defaults to 1 to enable metal support, 0 to  |
| `numThread` | number |  | Sets the number of threads to use during computation. By default, Ollama will detect this for optima |
| `repeatLastN` | number |  | Sets how far back for the model to look back to prevent repetition. (Default: 64, 0 = disabled, -1 = |
| `repeatPenalty` | number |  | Sets how strongly to penalize repetitions. A higher value (e.g., 1.5) will penalize repetitions more |
| `stop` | string |  | Sets the stop sequences to use. Use comma to seperate different sequences. Refer to <a target="_blan |
| `tfsZ` | number |  | Tail free sampling is used to reduce the impact of less probable tokens from the output. A higher va |

</details>

---

### OpenAI (`openAI`)

**Version:** 4  
**Description:** Wrapper around OpenAI large language models  
**Base Classes:** `OpenAI`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (openAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | asyncOptions | gpt-3.5-turbo-instruct | Model Name |
| `temperature` | number | 0.7 | Temperature |

<details>
<summary><b>Additional Parameters</b> (9 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Max Tokens |
| `topP` | number |  | Top Probability |
| `bestOf` | number |  | Best Of |
| `frequencyPenalty` | number |  | Frequency Penalty |
| `presencePenalty` | number |  | Presence Penalty |
| `batchSize` | number |  | Batch Size |
| `timeout` | number |  | Timeout |
| `basepath` | string |  | BasePath |
| `baseOptions` | json |  | BaseOptions |

</details>

---

### Replicate (`replicate`)

**Version:** 2  
**Description:** Use Replicate to run open source models on cloud  
**Base Classes:** `Replicate`, `BaseChatModel`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (replicateApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `model` | string |  | Model |
| `temperature` | number | 0.7 | Adjusts randomness of outputs, greater than 1 is random and 0 is deterministic, 0.75 is a good start |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Maximum number of tokens to generate. A word is generally 2-3 tokens |
| `topP` | number |  | When decoding text, samples from the top p percentage of most likely tokens; lower to ignore less li |
| `repetitionPenalty` | number |  | Penalty for repeated words in generated text; 1 is no penalty, values greater than 1 discourage repe |
| `additionalInputs` | json |  | Each model has different parameters, refer to the specific model accepted inputs. For example: <a ta |

</details>

---

### Sambanova (`sambanova`)

**Version:** 1  
**Description:** Wrapper around Sambanova API for large language models  
**Base Classes:** `Sambanova`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (sambanovaApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string | Meta-Llama-3.3-70B-Instruct | For more details see https://docs.sambanova.ai/cloud/docs/get-started/supported-models |

---

### TogetherAI (`togetherAI`)

**Version:** 1  
**Description:** Wrapper around TogetherAI large language models  
**Base Classes:** `TogetherAI`, `LLM`, `BaseLLM`, `BaseLanguageModel`, `Runnable`  

**Credential Required:** Connect Credential (togetherAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `cache` | BaseCache |  | Cache |
| `modelName` | string |  | The name of the model to query. |
| `topK` | number | 50 | The topK parameter is used to limit the number of choices for the next predicted word or token. It s |
| `topP` | number | 0.7 | The topP (nucleus) parameter is used to dynamically adjust the number of choices for each predicted  |
| `temperature` | number | 0.7 | A decimal number that determines the degree of randomness in the response. A value of 1 will always  |
| `repeatPenalty` | number | 1 | A number that controls the diversity of generated text by reducing the likelihood of repeated sequen |
| `streaming` | boolean | False | Whether or not to stream tokens as they are generated |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxTokens` | number |  | Limit the number of tokens generated. |
| `stop` | string |  | A list of tokens at which the generation should stop. |

</details>

---

## Memory (15)

### DynamoDB Chat Memory (`DynamoDBChatMemory`)

**Version:** 1  
**Description:** Stores the conversation in dynamo db table  
**Base Classes:** `DynamoDBChatMemory`, `BaseChatMemory`, `BaseMemory`  

**Credential Required:** Connect Credential (dynamodbMemoryApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tableName` | string |  | Table Name |
| `partitionKey` | string |  | Partition Key |
| `region` | string |  | The aws region in which table is located |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `memoryKey` | string | chat_history | Memory Key |

</details>

---

### MongoDB Atlas Chat Memory (`MongoDBAtlasChatMemory`)

**Version:** 1  
**Description:** Stores the conversation in MongoDB Atlas  
**Base Classes:** `MongoDBAtlasChatMemory`, `BaseChatMemory`, `BaseMemory`  

**Credential Required:** Connect Credential (mongoDBUrlApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `databaseName` | string |  | Database |
| `collectionName` | string |  | Collection Name |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `memoryKey` | string | chat_history | Memory Key |

</details>

---

### Redis-Backed Chat Memory (`RedisBackedChatMemory`)

**Version:** 2  
**Description:** Summarizes the conversation and stores the memory in Redis server  
**Base Classes:** `RedisBackedChatMemory`, `BaseChatMemory`, `BaseMemory`  

**Credential Required:** Connect Credential (redisCacheApi, redisCacheUrlApi)

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `sessionTTL` | number |  | Seconds till a session expires. If not specified, the session will never expire. |
| `memoryKey` | string | chat_history | Memory Key |
| `windowSize` | number |  | Window of size k to surface the last k back-and-forth to use as memory. |

</details>

---

### Zep Memory - Open Source (`ZepMemory`)

**Version:** 2  
**Description:** Summarizes the conversation and stores the memory in zep server  
**Base Classes:** `ZepMemory`, `BaseChatMemory`, `BaseMemory`  

**Credential Required:** Connect Credential (zepMemoryApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseURL` | string | http://127.0.0.1:8000 | Base URL |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `k` | number | 10 | Window of size k to surface the last k back-and-forth to use as memory. |
| `aiPrefix` | string | ai | AI Prefix |
| `humanPrefix` | string | human | Human Prefix |
| `memoryKey` | string | chat_history | Memory Key |
| `inputKey` | string | input | Input Key |
| `outputKey` | string | text | Output Key |

</details>

---

### Zep Memory - Cloud (`ZepMemoryCloud`)

**Version:** 2  
**Description:** Summarizes the conversation and stores the memory in zep server  
**Base Classes:** `ZepMemory`, `BaseChatMemory`, `BaseMemory`  

**Credential Required:** Connect Credential (zepMemoryApi)

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `memoryType` | string | perpetual | Zep Memory Type, can be perpetual or message_window |
| `aiPrefix` | string | ai | AI Prefix |
| `humanPrefix` | string | human | Human Prefix |
| `memoryKey` | string | chat_history | Memory Key |
| `inputKey` | string | input | Input Key |
| `outputKey` | string | text | Output Key |

</details>

---

### Agent Memory (`agentMemory`)

**Version:** 2  
**Description:** Memory for agentflow to remember the state of the conversation  
**Base Classes:** `AgentMemory`, `BaseCheckpointSaver`  

**Credential Required:** Connect Credential (PostgresApi, MySQLApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `databaseType` | options | sqlite | Database |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `databaseFilePath` | string |  | If SQLite is selected, provide the path to the SQLite database file. Leave empty to use default appl |
| `host` | string |  | If PostgresQL/MySQL is selected, provide the host of the database |
| `database` | string |  | If PostgresQL/MySQL is selected, provide the name of the database |
| `port` | number |  | If PostgresQL/MySQL is selected, provide the port of the database |
| `additionalConfig` | json |  | Additional Connection Configuration |

</details>

---

### Buffer Memory (`bufferMemory`)

**Version:** 2  
**Description:** Retrieve chat messages stored in database  
**Base Classes:** `BufferMemory`, `BaseChatMemory`, `BaseMemory`  

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `memoryKey` | string | chat_history | Memory Key |

</details>

---

### Buffer Window Memory (`bufferWindowMemory`)

**Version:** 2  
**Description:** Uses a window of size k to surface the last k back-and-forth to use as memory  
**Base Classes:** `BufferWindowMemory`, `BaseChatMemory`, `BaseMemory`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `k` | number | 4 | Window of size k to surface the last k back-and-forth to use as memory. |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `memoryKey` | string | chat_history | Memory Key |

</details>

---

### Conversation Summary Buffer Memory (`conversationSummaryBufferMemory`)

**Version:** 1  
**Description:** Uses token length to decide when to summarize conversations  
**Base Classes:** `ConversationSummaryBufferMemory`, `BaseConversationSummaryMemory`, `BaseChatMemory`, `BaseMemory`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel |  | Chat Model |
| `maxTokenLimit` | number | 2000 | Summarize conversations once token limit is reached. Default to 2000 |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `memoryKey` | string | chat_history | Memory Key |

</details>

---

### Conversation Summary Memory (`conversationSummaryMemory`)

**Version:** 2  
**Description:** Summarizes the conversation and stores the current summary in memory  
**Base Classes:** `ConversationSummaryMemory`, `BaseConversationSummaryMemory`, `BaseChatMemory`, `BaseMemory`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel |  | Chat Model |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `memoryKey` | string | chat_history | Memory Key |

</details>

---

### Mem0 (`mem0`)

**Version:** 1.1  
**Description:** Stores and manages chat memory using Mem0 service  
**Base Classes:** `Mem0`, `BaseChatMemory`, `BaseMemory`  

**Credential Required:** Connect Credential (mem0MemoryApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `user_id` | string | flowise-default-user | Unique identifier for the user. Required only if "Use Flowise Chat ID" is OFF. |
| `useFlowiseChatId` | boolean | False | Use the Flowise internal Chat ID as the Mem0 User ID, overriding the "User ID" field above. |

<details>
<summary><b>Additional Parameters</b> (9 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `searchOnly` | boolean | False | Search only mode |
| `run_id` | string |  | Unique identifier for the run session |
| `agent_id` | string |  | Identifier for the agent |
| `app_id` | string |  | Identifier for the application |
| `project_id` | string |  | Identifier for the project |
| `org_id` | string |  | Identifier for the organization |
| `memoryKey` | string | history | Memory Key |
| `inputKey` | string | input | Input Key |
| `outputKey` | string | text | Output Key |

</details>

---

### MySQL Agent Memory (`mySQLAgentMemory`)

**Version:** 1  
**Description:** Memory for agentflow to remember the state of the conversation using MySQL database  
**Base Classes:** `AgentMemory`, `BaseCheckpointSaver`  

**Credential Required:** Connect Credential (MySQLApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `host` | string |  | Host |
| `database` | string |  | Database |
| `port` | number | 3306 | Port |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `additionalConfig` | json |  | Additional Connection Configuration |

</details>

---

### Postgres Agent Memory (`postgresAgentMemory`)

**Version:** 1  
**Description:** Memory for agentflow to remember the state of the conversation using Postgres database  
**Base Classes:** `AgentMemory`, `BaseCheckpointSaver`  

**Credential Required:** Connect Credential (PostgresApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `host` | string |  | Host |
| `database` | string |  | Database |
| `port` | number | 5432 | Port |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `additionalConfig` | json |  | Additional Connection Configuration |

</details>

---

### SQLite Agent Memory (`sqliteAgentMemory`)

**Version:** 1  
**Description:** Memory for agentflow to remember the state of the conversation using SQLite database  
**Base Classes:** `SQLiteAgentMemory`, `BaseCheckpointSaver`  

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `additionalConfig` | json |  | Additional Connection Configuration |

</details>

---

### Upstash Redis-Backed Chat Memory (`upstashRedisBackedChatMemory`)

**Version:** 2  
**Description:** Summarizes the conversation and stores the memory in Upstash Redis server  
**Base Classes:** `UpstashRedisBackedChatMemory`, `BaseChatMemory`, `BaseMemory`  

**Credential Required:** Connect Credential (upstashRedisMemoryApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseURL` | string |  | Upstash Redis REST URL |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `sessionId` | string |  | If not specified, a random id will be used. Learn <a target="_blank" href="https://docs.flowiseai.co |
| `sessionTTL` | number |  | Seconds till a session expires. If not specified, the session will never expire. |
| `memoryKey` | string | chat_history | Memory Key |

</details>

---

## Moderation (2)

### OpenAI Moderation (`inputModerationOpenAI`)

**Version:** 1  
**Description:** Check whether content complies with OpenAI usage policies.  
**Base Classes:** `Moderation`  

**Credential Required:** Connect Credential (openAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `moderationErrorMessage` | string | Cannot Process! Input violates OpenAI's content moderation policies. | Error Message |

---

### Simple Prompt Moderation (`inputModerationSimple`)

**Version:** 2  
**Description:** Check whether input consists of any text from Deny list, and prevent being sent to LLM  
**Base Classes:** `Moderation`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `denyList` | string |  | An array of string literals (enter one per line) that should not appear in the prompt text. |
| `model` | BaseChatModel |  | Use LLM to detect if the input is similar to those specified in Deny List |
| `moderationErrorMessage` | string | Cannot Process! Input violates content moderation policies. | Error Message |

---

## Multi Agents (2)

### Supervisor (`supervisor`)

**Version:** 3  
**Description:** No description  
**Base Classes:** `Supervisor`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `supervisorName` | string | Supervisor | Supervisor Name |
| `model` | BaseChatModel |  | Only compatible with models that are capable of function calling: ChatOpenAI, ChatMistral, ChatAnthr |
| `agentMemory` | BaseCheckpointSaver |  | Save the state of the agent |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `supervisorPrompt` | string | You are a supervisor tasked with managing a conversation between the following workers: {team_members}.
Given the following user request, respond with the worker to act next.
Each worker will perform a task and respond with their results and status.
When finished, respond with FINISH.
Select strategically to minimize the number of steps taken. | Prompt must contains {team_members} |
| `summarization` | boolean |  | Return final output as a summarization of the conversation |
| `recursionLimit` | number | 100 | Maximum number of times a call can recurse. If not provided, defaults to 100. |

</details>

---

### Worker (`worker`)

**Version:** 2  
**Description:** No description  
**Base Classes:** `Worker`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `workerName` | string |  | Worker Name |
| `workerPrompt` | string | You are a research assistant who can search for up-to-date info using search engine. | Worker Prompt |
| `tools` | Tool |  | Tools |
| `supervisor` | Supervisor |  | Supervisor |
| `model` | BaseChatModel |  | Only compatible with models that are capable of function calling: ChatOpenAI, ChatMistral, ChatAnthr |
| `promptValues` | json |  | Format Prompt Values |
| `maxIterations` | number |  | Max Iterations |

---

## Output Parsers (4)

### Advanced Structured Output Parser (`advancedStructuredOutputParser`)

**Version:** 1  
**Description:** Parse the output of an LLM call into a given structure by providing a Zod schema.  
**Base Classes:** `AdvancedStructuredOutputParser`, `BaseLLMOutputParser`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `autofixParser` | boolean |  | In the event that the first call fails, will make another call to the model to fix any errors. |
| `exampleJson` | string | z.object({
    title: z.string(), // Title of the movie as a string
    yearOfRelease: z.number().int(), // Release year as an integer number,
    genres: z.enum([
        "Action", "Comedy", "Drama", "Fantasy", "Horror",
        "Mystery", "Romance", "Science Fiction", "Thriller", "Documentary"
    ]).array().max(2), // Array of genres, max of 2 from the defined enum
    shortDescription: z.string().max(500) // Short description, max 500 characters
}) | Zod schema for the output of the model |

---

### CSV Output Parser (`csvOutputParser`)

**Version:** 1  
**Description:** Parse the output of an LLM call as a comma-separated list of values  
**Base Classes:** `CSVListOutputParser`, `BaseLLMOutputParser`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `autofixParser` | boolean |  | In the event that the first call fails, will make another call to the model to fix any errors. |

---

### Custom List Output Parser (`customListOutputParser`)

**Version:** 1  
**Description:** Parse the output of an LLM call as a list of values.  
**Base Classes:** `CustomListOutputParser`, `BaseLLMOutputParser`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `length` | number |  | Number of values to return |
| `separator` | string | , | Separator between values |
| `autofixParser` | boolean |  | In the event that the first call fails, will make another call to the model to fix any errors. |

---

### Structured Output Parser (`structuredOutputParser`)

**Version:** 1  
**Description:** Parse the output of an LLM call into a given (JSON) structure.  
**Base Classes:** `StructuredOutputParser`, `BaseLLMOutputParser`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `autofixParser` | boolean |  | In the event that the first call fails, will make another call to the model to fix any errors. |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `jsonStructure` | datagrid | [{'property': 'answer', 'type': 'string', 'description': "answer to the user's question"}, {'property': 'source', 'type': 'string', 'description': 'sources used to answer the question, should be websites'}] | JSON structure for LLM to return |

</details>

---

## Prompts (3)

### Chat Prompt Template (`chatPromptTemplate`)

**Version:** 2  
**Description:** Schema to represent a chat prompt  
**Base Classes:** `ChatPromptTemplate`, `BaseChatPromptTemplate`, `BasePromptTemplate`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessagePrompt` | string |  | System Message |
| `humanMessagePrompt` | string |  | This prompt will be added at the end of the messages as human message |
| `promptValues` | json |  | Format Prompt Values |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `messageHistory` | tabs | messageHistoryCode | Add messages after System Message. This is useful when you want to provide few shot examples |

</details>

---

### Few Shot Prompt Template (`fewShotPromptTemplate`)

**Version:** 1  
**Description:** Prompt template you can build with examples  
**Base Classes:** `FewShotPromptTemplate`, `BaseStringPromptTemplate`, `BasePromptTemplate`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `examples` | string |  | Examples |
| `examplePrompt` | PromptTemplate |  | Example Prompt |
| `prefix` | string |  | Prefix |
| `suffix` | string |  | Suffix |
| `exampleSeparator` | string |  | Example Separator |
| `templateFormat` | options | f-string | Template Format |

---

### Prompt Template (`promptTemplate`)

**Version:** 1  
**Description:** Schema to represent a basic prompt for an LLM  
**Base Classes:** `PromptTemplate`, `BaseStringPromptTemplate`, `BasePromptTemplate`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `template` | string |  | Template |
| `promptValues` | json |  | Format Prompt Values |

---

## Record Manager (3)

### MySQL Record Manager (`MySQLRecordManager`)

**Version:** 1  
**Description:** Use MySQL to keep track of document writes into the vector databases  
**Base Classes:** `MySQL RecordManager`, `RecordManager`  

**Credential Required:** Connect Credential (MySQLApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `host` | string |  | Host |
| `database` | string |  | Database |
| `port` | number |  | Port |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `additionalConfig` | json |  | Additional Connection Configuration |
| `tableName` | string |  | Table Name |
| `namespace` | string |  | Namespace |
| `cleanup` | options | none | Read more on the difference between different cleanup methods <a target="_blank" href="https://js.la |
| `sourceIdKey` | string | source | Key used to get the true source of document, to be compared against the record. Document metadata mu |

</details>

---

### SQLite Record Manager (`SQLiteRecordManager`)

**Version:** 1.1  
**Description:** Use SQLite to keep track of document writes into the vector databases  
**Base Classes:** `SQLite RecordManager`, `RecordManager`  

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `additionalConfig` | json |  | Additional Connection Configuration |
| `tableName` | string |  | Table Name |
| `namespace` | string |  | Namespace |
| `cleanup` | options | none | Read more on the difference between different cleanup methods <a target="_blank" href="https://js.la |
| `sourceIdKey` | string | source | Key used to get the true source of document, to be compared against the record. Document metadata mu |

</details>

---

### Postgres Record Manager (`postgresRecordManager`)

**Version:** 1  
**Description:** Use Postgres to keep track of document writes into the vector databases  
**Base Classes:** `Postgres RecordManager`, `RecordManager`  

**Credential Required:** Connect Credential (PostgresApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `host` | string |  | Host |
| `database` | string |  | Database |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `port` | number |  | Port |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `ssl` | boolean |  | Use SSL to connect to Postgres |
| `additionalConfig` | json |  | Additional Connection Configuration |
| `tableName` | string |  | Table Name |
| `namespace` | string |  | Namespace |
| `cleanup` | options | none | Read more on the difference between different cleanup methods <a target="_blank" href="https://js.la |
| `sourceIdKey` | string | source | Key used to get the true source of document, to be compared against the record. Document metadata mu |

</details>

---

## Response Synthesizer (4)

### Compact and Refine (`compactrefineLlamaIndex`)

**Version:** 1  
**Description:** CompactRefine is a slight variation of Refine that first compacts the text chunks into the smallest possible number of chunks.  
**Base Classes:** `CompactRefine`, `ResponseSynthesizer`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `refinePrompt` | string | The original query is as follows: {query}
We have provided an existing answer: {existingAnswer}
We have the opportunity to refine the existing answer (only if needed) with some more context below.
------------
{context}
------------
Given the new context, refine the original answer to better answer the query. If the context isn't useful, return the original answer.
Refined Answer: | Refine Prompt |
| `textQAPrompt` | string | Context information is below.
---------------------
{context}
---------------------
Given the context information and not prior knowledge, answer the query.
Query: {query}
Answer: | Text QA Prompt |

---

### Refine (`refineLlamaIndex`)

**Version:** 1  
**Description:** Create and refine an answer by sequentially going through each retrieved text chunk. This makes a separate LLM call per Node. Good for more detailed answers.  
**Base Classes:** `Refine`, `ResponseSynthesizer`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `refinePrompt` | string | The original query is as follows: {query}
We have provided an existing answer: {existingAnswer}
We have the opportunity to refine the existing answer (only if needed) with some more context below.
------------
{context}
------------
Given the new context, refine the original answer to better answer the query. If the context isn't useful, return the original answer.
Refined Answer: | Refine Prompt |
| `textQAPrompt` | string | Context information is below.
---------------------
{context}
---------------------
Given the context information and not prior knowledge, answer the query.
Query: {query}
Answer: | Text QA Prompt |

---

### Simple Response Builder (`simpleResponseBuilderLlamaIndex`)

**Version:** 1  
**Description:** Apply a query to a collection of text chunks, gathering the responses in an array, and return a combined string of all responses. Useful for individual queries on each text chunk.  
**Base Classes:** `SimpleResponseBuilder`, `ResponseSynthesizer`  

*No configurable inputs.*

---

### TreeSummarize (`treeSummarizeLlamaIndex`)

**Version:** 1  
**Description:** Given a set of text chunks and the query, recursively construct a tree and return the root node as the response. Good for summarization purposes.  
**Base Classes:** `TreeSummarize`, `ResponseSynthesizer`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `prompt` | string | Context information from multiple sources is below.
---------------------
{context}
---------------------
Given the information from multiple sources and not prior knowledge, answer the query.
Query: {query}
Answer: | Prompt |

---

## Retrievers (15)

### Azure Rerank Retriever (`AzureRerankRetriever`)

**Version:** 1  
**Description:** Azure Rerank indexes the documents from most to least semantically relevant to the query.  
**Base Classes:** `Azure Rerank Retriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (azureFoundryApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseRetriever` | VectorStoreRetriever |  | Vector Store Retriever |
| `model` | options | Cohere-rerank-v4.0-fast | Model Name |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number |  | Number of top results to fetch. Default to the TopK of the Base Retriever |
| `maxChunksPerDoc` | number |  | The maximum number of chunks to produce internally from a document. Default to 10 |

</details>

---

### HyDE Retriever (`HydeRetriever`)

**Version:** 3  
**Description:** Use HyDE retriever to retrieve from a vector store  
**Base Classes:** `HydeRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `vectorStore` | VectorStore |  | Vector Store |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |
| `promptKey` | options | websearch | Select a pre-defined prompt |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `customPrompt` | string |  | If custom prompt is used, this will override Defined Prompt |
| `topK` | number | 4 | Number of top results to fetch. Default to 4 |

</details>

---

### Jina AI Rerank Retriever (`JinaRerankRetriever`)

**Version:** 1  
**Description:** Jina AI Rerank indexes the documents from most to least semantically relevant to the query.  
**Base Classes:** `JinaRerankRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (jinaAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseRetriever` | VectorStoreRetriever |  | Vector Store Retriever |
| `model` | options | jina-reranker-v2-base-multilingual | Model Name |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topN` | number | 4 | Number of top results to fetch. Default to 4 |

</details>

---

### Reciprocal Rank Fusion Retriever (`RRFRetriever`)

**Version:** 1  
**Description:** Reciprocal Rank Fusion to re-rank search results by multiple query generation.  
**Base Classes:** `RRFRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseRetriever` | VectorStoreRetriever |  | Vector Store Retriever |
| `model` | BaseLanguageModel |  | Language Model |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `queryCount` | number | 4 | Number of synthetic queries to generate. Default to 4 |
| `topK` | number |  | Number of top results to fetch. Default to the TopK of the Base Retriever |
| `c` | number | 60 | A constant added to the rank, controlling the balance between the importance of high-ranked items an |

</details>

---

### AWS Bedrock Knowledge Base Retriever (`awsBedrockKBRetriever`)

**Version:** 1  
**Description:** Connect to AWS Bedrock Knowledge Base API and retrieve relevant chunks  
**Base Classes:** `AWSBedrockKBRetriever`, `BaseRetriever`  

**Credential Required:** AWS Credential (awsApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `region` | asyncOptions | us-east-1 | Region |
| `knoledgeBaseID` | string |  | Knowledge Base ID |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number | 5 | Number of chunks to retrieve |
| `searchType` | options |  | Knowledge Base search type. Possible values are HYBRID and SEMANTIC. If not specified, default will  |
| `filter` | string |  | Knowledge Base retrieval filter. Read documentation for filter syntax |

</details>

---

### Cohere Rerank Retriever (`cohereRerankRetriever`)

**Version:** 1  
**Description:** Cohere Rerank indexes the documents from most to least semantically relevant to the query.  
**Base Classes:** `Cohere Rerank Retriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (cohereApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseRetriever` | VectorStoreRetriever |  | Vector Store Retriever |
| `model` | options | rerank-v3.5 | Model Name |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number |  | Number of top results to fetch. Default to the TopK of the Base Retriever |
| `maxChunksPerDoc` | number |  | The maximum number of chunks to produce internally from a document. Default to 10 |

</details>

---

### Custom Retriever (`customRetriever`)

**Version:** 1  
**Description:** Return results based on predefined format  
**Base Classes:** `CustomRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `vectorStore` | VectorStore |  | Vector Store |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |
| `resultFormat` | string | {{context}}
Source: {{metadata.source}} | Format to return the results in. Use {{context}} to insert the pageContent of the document and {{met |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number |  | Number of top results to fetch. Default to vector store topK |

</details>

---

### Embeddings Filter Retriever (`embeddingsFilterRetriever`)

**Version:** 1  
**Description:** A document compressor that uses embeddings to drop documents unrelated to the query  
**Base Classes:** `EmbeddingsFilterRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseRetriever` | VectorStoreRetriever |  | Vector Store Retriever |
| `embeddings` | Embeddings |  | Embeddings |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |
| `similarityThreshold` | number | 0.8 | Threshold for determining when two documents are similar enough to be considered redundant. Must be  |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `k` | number | 20 | The number of relevant documents to return. Can be explicitly set to undefined, in which case simila |

</details>

---

### Extract Metadata Retriever (`extractMetadataRetriever`)

**Version:** 1  
**Description:** Extract keywords/metadata from the query and use it to filter documents  
**Base Classes:** `ExtractMetadataRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `vectorStore` | VectorStore |  | Vector Store |
| `model` | BaseChatModel |  | Chat Model |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `dynamicMetadataFilterRetrieverPrompt` | string | Extract keywords from the query: {{query}} | Prompt to extract metadata from query |
| `dynamicMetadataFilterRetrieverStructuredOutput` | datagrid |  | Instruct the model to give output in a JSON structured schema. This output will be used as the metad |
| `topK` | number |  | Number of top results to fetch. Default to vector store topK |

</details>

---

### LLM Filter Retriever (`llmFilterRetriever`)

**Version:** 1  
**Description:** Iterate over the initially returned documents and extract, from each, only the content that is relevant to the query  
**Base Classes:** `LLMFilterRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseRetriever` | VectorStoreRetriever |  | Vector Store Retriever |
| `model` | BaseLanguageModel |  | Language Model |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |

---

### Multi Query Retriever (`multiQueryRetriever`)

**Version:** 1  
**Description:** Generate multiple queries from different perspectives for a given user input query  
**Base Classes:** `MultiQueryRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `vectorStore` | VectorStore |  | Vector Store |
| `model` | BaseLanguageModel |  | Language Model |
| `modelPrompt` | string | You are an AI language model assistant. Your task is
to generate 3 different versions of the given user
question to retrieve relevant documents from a vector database.
By generating multiple perspectives on the user question,
your goal is to help the user overcome some of the limitations
of distance-based similarity search.

Provide these alternative questions separated by newlines between XML tags. For example:

<questions>
Question 1
Question 2
Question 3
</questions>

Original question: {question} | Prompt for the language model to generate alternative questions. Use {question} to refer to the orig |

---

### Prompt Retriever (`promptRetriever`)

**Version:** 1  
**Description:** Store prompt template with name & description to be later queried by MultiPromptChain  
**Base Classes:** `PromptRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string |  | Prompt Name |
| `description` | string |  | Description of what the prompt does and when it should be used |
| `systemMessage` | string |  | Prompt System Message |

---

### Similarity Score Threshold Retriever (`similarityThresholdRetriever`)

**Version:** 2  
**Description:** Return results based on the minimum similarity percentage  
**Base Classes:** `SimilarityThresholdRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `vectorStore` | VectorStore |  | Vector Store |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |
| `minSimilarityScore` | number | 80 | Finds results with at least this similarity score |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxK` | number | 20 | The maximum number of results to fetch |
| `kIncrement` | number | 2 | How much to increase K by each time. It'll fetch N results, then N + kIncrement, then N + kIncrement |

</details>

---

### Vector Store Retriever (`vectorStoreRetriever`)

**Version:** 1  
**Description:** Store vector store as retriever to be later queried by MultiRetrievalQAChain  
**Base Classes:** `VectorStoreRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `vectorStore` | VectorStore |  | Vector Store |
| `name` | string |  | Retriever Name |
| `description` | string |  | Description of when to use the vector store retriever |

---

### Voyage AI Rerank Retriever (`voyageAIRerankRetriever`)

**Version:** 1  
**Description:** Voyage AI Rerank indexes the documents from most to least semantically relevant to the query.  
**Base Classes:** `VoyageAIRerankRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (voyageAIApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseRetriever` | VectorStoreRetriever |  | Vector Store Retriever |
| `model` | options | rerank-lite-1 | Model Name |
| `query` | string |  | Query to retrieve documents from retriever. If not specified, user question will be used |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number |  | Number of top results to fetch. Default to the TopK of the Base Retriever |

</details>

---

## Sequential Agents (11)

### Agent (`seqAgent`)

**Version:** 4.1  
**Description:** Agent that can execute tools  
**Base Classes:** `Agent`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `agentName` | string |  | Agent Name |
| `systemMessagePrompt` | string | You are a research assistant who can search for up-to-date info using search engine. | System Prompt |
| `tools` | Tool |  | Tools |
| `sequentialNode` | Start \| Agent \| Condition \| LLMNode \| ToolNode \| CustomFunction \| ExecuteFlow |  | Can be connected to one of the following nodes: Start, Agent, Condition, LLM Node, Tool Node, Custom |
| `model` | BaseChatModel |  | Overwrite model to be used for this agent |
| `interrupt` | boolean |  | Pause execution and request user approval before running tools.
If enabled, the agent will prompt th |
| `promptValues` | json |  | Assign values to the prompt variables. You can also use $flow.state.<variable-name> to get the state |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `messageHistory` | code |  | Prepend a list of messages between System Prompt and Human Prompt. This is useful when you want to p |
| `conversationHistorySelection` | options | all_messages | Select which messages from the conversation history to include in the prompt. The selected messages  |
| `humanMessagePrompt` | string |  | This prompt will be added at the end of the messages as human message |
| `approvalPrompt` | string | You are about to execute tool: {tools}. Ask if user want to proceed | Prompt for approval. Only applicable if "Require Approval" is enabled |
| `approveButtonText` | string | Yes | Text for approve button. Only applicable if "Require Approval" is enabled |
| `rejectButtonText` | string | No | Text for reject button. Only applicable if "Require Approval" is enabled |
| `updateStateMemory` | tabs | updateStateMemoryUI | Update State |
| `maxIterations` | number |  | Max Iterations |

</details>

---

### Condition (`seqCondition`)

**Version:** 2.1  
**Description:** Conditional function to determine which route to take next  
**Base Classes:** `Condition`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `conditionName` | string |  | Condition Name |
| `sequentialNode` | Start \| Agent \| LLMNode \| ToolNode \| CustomFunction \| ExecuteFlow |  | Can be connected to one of the following nodes: Start, Agent, LLM Node, Tool Node, Custom Function,  |
| `condition` | conditionFunction |  | Condition |

---

### Condition Agent (`seqConditionAgent`)

**Version:** 3.1  
**Description:** Uses an agent to determine which route to take next  
**Base Classes:** `ConditionAgent`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `conditionAgentName` | string |  | Name |
| `sequentialNode` | Start \| Agent \| LLMNode \| ToolNode \| CustomFunction \| ExecuteFlow |  | Can be connected to one of the following nodes: Start, Agent, LLM Node, Tool Node, Custom Function,  |
| `model` | BaseChatModel |  | Overwrite model to be used for this agent |
| `condition` | conditionFunction |  | Condition |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessagePrompt` | string | You are an expert customer support routing system.
Your job is to detect whether a customer support representative is routing a user to the technical support team, or just responding conversationally. | System Prompt |
| `conversationHistorySelection` | options | all_messages | Select which messages from the conversation history to include in the prompt. The selected messages  |
| `humanMessagePrompt` | string | The previous conversation is an interaction between a customer support representative and a user.
Extract whether the representative is routing the user to the technical support team, or just responding conversationally.

If representative want to route the user to the technical support team, respond only with the word "TECHNICAL".
Otherwise, respond only with the word "CONVERSATION".

Remember, only respond with one of the above words. | This prompt will be added at the end of the messages as human message |
| `promptValues` | json |  | Assign values to the prompt variables. You can also use $flow.state.<variable-name> to get the state |
| `conditionAgentStructuredOutput` | datagrid |  | Instruct the LLM to give output in a JSON structured schema |

</details>

---

### Custom JS Function (`seqCustomFunction`)

**Version:** 1  
**Description:** Execute custom javascript function  
**Base Classes:** `CustomFunction`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `functionInputVariables` | json |  | Input variables can be used in the function with prefix $. For example: $var |
| `sequentialNode` | Start \| Agent \| Condition \| LLMNode \| ToolNode \| CustomFunction \| ExecuteFlow |  | Can be connected to one of the following nodes: Start, Agent, Condition, LLM Node, Tool Node, Custom |
| `functionName` | string |  | Function Name |
| `javascriptFunction` | code |  | Javascript Function |
| `returnValueAs` | options | aiMessage | Return Value As |

---

### End (`seqEnd`)

**Version:** 2.1  
**Description:** End conversation  
**Base Classes:** `End`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `sequentialNode` | Agent \| Condition \| LLMNode \| ToolNode \| CustomFunction \| ExecuteFlow |  | Can be connected to one of the following nodes: Agent, Condition, LLM Node, Tool Node, Custom Functi |

---

### Execute Flow (`seqExecuteFlow`)

**Version:** 1  
**Description:** Execute chatflow/agentflow and return final response  
**Base Classes:** `ExecuteFlow`  

**Credential Required:** Connect Credential (chatflowApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `sequentialNode` | Start \| Agent \| Condition \| LLMNode \| ToolNode \| CustomFunction \| ExecuteFlow |  | Can be connected to one of the following nodes: Start, Agent, Condition, LLM Node, Tool Node, Custom |
| `seqExecuteFlowName` | string |  | Name |
| `selectedFlow` | asyncOptions |  | Select Flow |
| `seqExecuteFlowInput` | options |  | Select one of the following or enter custom input |
| `returnValueAs` | options | aiMessage | Return Value As |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `overrideConfig` | json |  | Override the config passed to the flow. |
| `baseURL` | string |  | Base URL to Flowise. By default, it is the URL of the incoming request. Useful when you need to exec |
| `startNewSession` | boolean | False | Whether to continue the session or start a new one with each interaction. Useful for flows with memo |

</details>

---

### LLM Node (`seqLLMNode`)

**Version:** 4.1  
**Description:** Run Chat Model and return the output  
**Base Classes:** `LLMNode`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `llmNodeName` | string |  | Name |
| `sequentialNode` | Start \| Agent \| Condition \| LLMNode \| ToolNode \| CustomFunction \| ExecuteFlow |  | Can be connected to one of the following nodes: Start, Agent, Condition, LLM, Tool Node, Custom Func |
| `model` | BaseChatModel |  | Overwrite model to be used for this node |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `systemMessagePrompt` | string |  | System Prompt |
| `messageHistory` | code |  | Prepend a list of messages between System Prompt and Human Prompt. This is useful when you want to p |
| `conversationHistorySelection` | options | all_messages | Select which messages from the conversation history to include in the prompt. The selected messages  |
| `humanMessagePrompt` | string |  | This prompt will be added at the end of the messages as human message |
| `promptValues` | json |  | Assign values to the prompt variables. You can also use $flow.state.<variable-name> to get the state |
| `llmStructuredOutput` | datagrid |  | Instruct the LLM to give output in a JSON structured schema |
| `updateStateMemory` | tabs | updateStateMemoryUI | Update State |

</details>

---

### Loop (`seqLoop`)

**Version:** 2.1  
**Description:** Loop back to the specific sequential node  
**Base Classes:** `Loop`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `sequentialNode` | Agent \| Condition \| LLMNode \| ToolNode \| CustomFunction \| ExecuteFlow |  | Can be connected to one of the following nodes: Agent, Condition, LLM Node, Tool Node, Custom Functi |
| `loopToName` | string |  | Name of the agent/llm to loop back to |

---

### Start (`seqStart`)

**Version:** 2  
**Description:** Starting point of the conversation  
**Base Classes:** `Start`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseChatModel |  | Only compatible with models that are capable of function calling: ChatOpenAI, ChatMistral, ChatAnthr |
| `agentMemory` | BaseCheckpointSaver |  | Save the state of the agent |
| `state` | State |  | State is an object that is updated by nodes in the graph, passing from one node to another. By defau |
| `inputModeration` | Moderation |  | Detect text that could generate harmful output and prevent it from being sent to the language model |

---

### State (`seqState`)

**Version:** 2  
**Description:** A centralized state object, updated by nodes in the graph, passing from one node to another  
**Base Classes:** `State`  

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `stateMemory` | tabs | stateMemoryUI | Custom State |

</details>

---

### Tool Node (`seqToolNode`)

**Version:** 2.1  
**Description:** Execute tool and return tool's output  
**Base Classes:** `ToolNode`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `tools` | Tool |  | Tools |
| `llmNode` | LLMNode |  | LLM Node |
| `toolNodeName` | string |  | Name |
| `interrupt` | boolean |  | Require approval before executing tools |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `approvalPrompt` | string | You are about to execute tool: {tools}. Ask if user want to proceed | Prompt for approval. Only applicable if "Require Approval" is enabled |
| `approveButtonText` | string | Yes | Text for approve button. Only applicable if "Require Approval" is enabled |
| `rejectButtonText` | string | No | Text for reject button. Only applicable if "Require Approval" is enabled |
| `updateStateMemory` | tabs | updateStateMemoryUI | Update State |

</details>

---

## Text Splitters (6)

### Character Text Splitter (`characterTextSplitter`)

**Version:** 1  
**Description:** splits only on one type of character (defaults to "\n\n").  
**Base Classes:** `CharacterTextSplitter`, `TextSplitter`, `BaseDocumentTransformer`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `chunkSize` | number | 1000 | Number of characters in each chunk. Default is 1000. |
| `chunkOverlap` | number | 200 | Number of characters to overlap between chunks. Default is 200. |
| `separator` | string |  | Separator to determine when to split the text, will override the default separator |

---

### Code Text Splitter (`codeTextSplitter`)

**Version:** 1  
**Description:** Split documents based on language-specific syntax  
**Base Classes:** `CodeTextSplitter`, `TextSplitter`, `BaseDocumentTransformer`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `language` | options |  | Language |
| `chunkSize` | number | 1000 | Number of characters in each chunk. Default is 1000. |
| `chunkOverlap` | number | 200 | Number of characters to overlap between chunks. Default is 200. |

---

### HtmlToMarkdown Text Splitter (`htmlToMarkdownTextSplitter`)

**Version:** 1  
**Description:** Converts Html to Markdown and then split your content into documents based on the Markdown headers  
**Base Classes:** `HtmlToMarkdownTextSplitter`, `MarkdownTextSplitter`, `RecursiveCharacterTextSplitter`, `TextSplitter`, `BaseDocumentTransformer`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `chunkSize` | number | 1000 | Number of characters in each chunk. Default is 1000. |
| `chunkOverlap` | number | 200 | Number of characters to overlap between chunks. Default is 200. |

---

### Markdown Text Splitter (`markdownTextSplitter`)

**Version:** 1.1  
**Description:** Split your content into documents based on the Markdown headers  
**Base Classes:** `MarkdownTextSplitter`, `RecursiveCharacterTextSplitter`, `TextSplitter`, `BaseDocumentTransformer`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `chunkSize` | number | 1000 | Number of characters in each chunk. Default is 1000. |
| `chunkOverlap` | number | 200 | Number of characters to overlap between chunks. Default is 200. |
| `splitByHeaders` | options | disabled | Split documents at specified header levels. Headers will be included with their content. |

---

### Recursive Character Text Splitter (`recursiveCharacterTextSplitter`)

**Version:** 2  
**Description:** Split documents recursively by different characters - starting with "\n\n", then "\n", then " "  
**Base Classes:** `RecursiveCharacterTextSplitter`, `TextSplitter`, `BaseDocumentTransformer`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `chunkSize` | number | 1000 | Number of characters in each chunk. Default is 1000. |
| `chunkOverlap` | number | 200 | Number of characters to overlap between chunks. Default is 200. |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `separators` | string |  | Array of custom separators to determine when to split the text, will override the default separators |

</details>

---

### Token Text Splitter (`tokenTextSplitter`)

**Version:** 1  
**Description:** Splits a raw text string by first converting the text into BPE tokens, then split these tokens into chunks and convert the tokens within a single chunk back into text.  
**Base Classes:** `TokenTextSplitter`, `TextSplitter`, `BaseDocumentTransformer`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `encodingName` | options | gpt2 | Encoding Name |
| `chunkSize` | number | 1000 | Number of characters in each chunk. Default is 1000. |
| `chunkOverlap` | number | 200 | Number of characters to overlap between chunks. Default is 200. |

---

## Tools (39)

### Chatflow Tool (`ChatflowTool`)

**Version:** 5.1  
**Description:** Use as a tool to execute another chatflow  
**Base Classes:** `ChatflowTool`, `Tool`  

**Credential Required:** Connect Credential (chatflowApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `selectedChatflow` | asyncOptions |  | Select Chatflow |
| `name` | string |  | Tool Name |
| `description` | string |  | Description of what the tool does. This is for LLM to determine when to use this tool. |
| `returnDirect` | boolean |  | Return Direct |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `overrideConfig` | json |  | Override the config passed to the Chatflow. |
| `baseURL` | string |  | Base URL to Flowise. By default, it is the URL of the incoming request. Useful when you need to exec |
| `startNewSession` | boolean | False | Whether to continue the session with the Chatflow tool or start a new one with each interaction. Use |
| `useQuestionFromChat` | boolean |  | Whether to use the question from the chat as input to the chatflow. If turned on, this will override |
| `customInput` | string |  | Custom input to be passed to the chatflow. Leave empty to let LLM decides the input. |

</details>

---

### Agent as Tool (`agentAsTool`)

**Version:** 1  
**Description:** Use as a tool to execute another agentflow  
**Base Classes:** `AgentAsTool`, `Tool`  

**Credential Required:** Connect Credential (agentflowApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `selectedAgentflow` | asyncOptions |  | Select Agent |
| `name` | string |  | Tool Name |
| `description` | string |  | Description of what the tool does. This is for LLM to determine when to use this tool. |
| `returnDirect` | boolean |  | Return Direct |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `overrideConfig` | json |  | Override the config passed to the Agentflow. |
| `baseURL` | string |  | Base URL to Flowise. By default, it is the URL of the incoming request. Useful when you need to exec |
| `startNewSession` | boolean | False | Whether to continue the session with the Agentflow tool or start a new one with each interaction. Us |
| `useQuestionFromChat` | boolean |  | Whether to use the question from the chat as input to the agentflow. If turned on, this will overrid |
| `customInput` | string |  | Custom input to be passed to the agentflow. Leave empty to let LLM decides the input. |

</details>

---

### Arxiv (`arxiv`)

**Version:** 1  
**Description:** Search and read content from academic papers on Arxiv  
**Base Classes:** `Arxiv`, `DynamicStructuredTool`, `StructuredTool`, `Runnable`  

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `arxivName` | string | arxiv_search | Name of the tool |
| `arxivDescription` | string | Use this tool to search for academic papers on Arxiv. You can search by keywords, topics, authors, or specific Arxiv IDs. The tool can return either paper summaries or download and extract full paper content. | Describe to LLM when it should use this tool |
| `topKResults` | number | 3 | Number of top results to return from Arxiv search |
| `maxQueryLength` | number | 300 | Maximum length of the search query |
| `docContentCharsMax` | number | 10000 | Maximum length of the returned content. Set to 0 for unlimited |
| `loadFullContent` | boolean | False | Download PDFs and extract full paper content instead of just summaries. Warning: This is slower and  |
| `continueOnFailure` | boolean | False | Continue processing other papers if one fails to download/parse (only applies when Load Full Content |
| `legacyBuild` | boolean | False | Use legacy PDF.js build for PDF parsing (only applies when Load Full Content is enabled) |

</details>

---

### AWS DynamoDB KV Storage (`awsDynamoDBKVStorage`)

**Version:** 1  
**Description:** Store and retrieve versioned text values in AWS DynamoDB  
**Base Classes:** `AWSDynamoDBKVStorage`, `StructuredTool`, `Runnable`  

**Credential Required:** AWS Credentials (awsApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `region` | options | us-east-1 | AWS Region where your DynamoDB tables are located |
| `tableName` | asyncOptions |  | Select a DynamoDB table with partition key "pk" and sort key "sk" |
| `operation` | options | store | Choose whether to store or retrieve data |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `keyPrefix` | string |  | Optional prefix to add to all keys (e.g., "myapp" would make keys like "myapp#userdata") |

</details>

---

### AWS SNS (`awsSNS`)

**Version:** 1  
**Description:** Publish messages to AWS SNS topics  
**Base Classes:** `AWSSNS`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** AWS Credentials (awsApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `region` | options | us-east-1 | AWS Region where your SNS topics are located |
| `topicArn` | asyncOptions |  | Select the SNS topic to publish to |

---

### BraveSearch API (`braveSearchAPI`)

**Version:** 1  
**Description:** Wrapper around BraveSearch API - a real-time API to access Brave search results  
**Base Classes:** `BraveSearchAPI`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (braveSearchApi)

*No configurable inputs.*

---

### Calculator (`calculator`)

**Version:** 1  
**Description:** Perform calculations on response  
**Base Classes:** `Calculator`, `Tool`, `StructuredTool`, `Runnable`  

*No configurable inputs.*

---

### Chain Tool (`chainTool`)

**Version:** 1  
**Description:** Use a chain as allowed tool for agent  
**Base Classes:** `ChainTool`, `DynamicTool`, `Tool`, `StructuredTool`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string |  | Chain Name |
| `description` | string |  | Chain Description |
| `returnDirect` | boolean |  | Return Direct |
| `baseChain` | BaseChain |  | Base Chain |

---

### Code Interpreter by E2B (`codeInterpreterE2B`)

**Version:** 1  
**Description:** Execute code in a sandbox environment  
**Base Classes:** `CodeInterpreter`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (E2BApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `toolName` | string | code_interpreter | Specify the name of the tool |
| `toolDesc` | string | Evaluates python code in a sandbox environment. The environment is long running and exists across multiple executions. You must send the whole script every time and print your outputs. Script should be pure python code that can be evaluated. It should be in python format NOT markdown. The code should NOT be wrapped in backticks. All python packages including requests, matplotlib, scipy, numpy, pandas, etc are available. Create and display chart using "plt.show()". | Specify the description of the tool |

---

### Composio (`composio`)

**Version:** 2  
**Description:** Toolset with over 250+ Apps for building AI-powered applications  
**Base Classes:** `Composio`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (composioApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `appName` | asyncOptions |  | Select the app to connect with |
| `connectedAccountId` | asyncOptions |  | Select which connection to use |
| `actions` | asyncMultiOptions |  | Select the actions you want to use |

---

### CurrentDateTime (`currentDateTime`)

**Version:** 1  
**Description:** Get todays day, date and time.  
**Base Classes:** `CurrentDateTime`, `Tool`  

*No configurable inputs.*

---

### Custom Tool (`customTool`)

**Version:** 3  
**Description:** Use custom tool you've created in Flowise within chatflow  
**Base Classes:** `CustomTool`, `Tool`, `StructuredTool`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `selectedTool` | asyncOptions |  | Select Tool |
| `returnDirect` | boolean |  | Return the output of the tool directly to the user |
| `customToolName` | string |  | Custom Tool Name |
| `customToolDesc` | string |  | Custom Tool Description |
| `customToolSchema` | string |  | Custom Tool Schema |
| `customToolFunc` | string |  | Custom Tool Func |

---

### Exa Search (`exaSearch`)

**Version:** 1.1  
**Description:** Wrapper around Exa Search API - search engine fully designed for use by LLMs  
**Base Classes:** `ExaSearch`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (exaSearchApi)

<details>
<summary><b>Additional Parameters</b> (11 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `description` | string | A wrapper around Exa Search. Input should be an Exa-optimized query. Output is a JSON array of the query results | Description of what the tool does. This is for LLM to determine when to use this tool. |
| `numResults` | number |  | Number of search results to return. Default 10. Max 10 for basic plans. Up to thousands for custom p |
| `type` | options |  | Search Type |
| `useAutoprompt` | boolean |  | If true, your query will be converted to a Exa query. Default false. |
| `category` | options |  | A data category to focus on, with higher comprehensivity and data cleanliness. Categories right now  |
| `includeDomains` | string |  | List of domains to include in the search, separated by comma. If specified, results will only come f |
| `excludeDomains` | string |  | List of domains to exclude in the search, separated by comma. If specified, results will not include |
| `startCrawlDate` | string |  | Crawl date refers to the date that Exa discovered a link. Results will include links that were crawl |
| `endCrawlDate` | string |  | Crawl date refers to the date that Exa discovered a link. Results will include links that were crawl |
| `startPublishedDate` | string |  | Only links with a published date after this will be returned. Must be specified in ISO 8601 format. |
| `endPublishedDate` | string |  | Only links with a published date before this will be returned. Must be specified in ISO 8601 format. |

</details>

---

### Gmail (`gmail`)

**Version:** 1  
**Description:** Perform Gmail operations for drafts, messages, labels, and threads  
**Base Classes:** `Gmail`, `Tool`  

**Credential Required:** Connect Credential (gmailOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `gmailType` | options |  | Type |
| `draftActions` | multiOptions |  | Draft Actions |
| `messageActions` | multiOptions |  | Message Actions |
| `labelActions` | multiOptions |  | Label Actions |
| `threadActions` | multiOptions |  | Thread Actions |

<details>
<summary><b>Additional Parameters</b> (28 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `draftMaxResults` | number | 100 | Maximum number of drafts to return |
| `draftTo` | string |  | Recipient email address(es), comma-separated |
| `draftSubject` | string |  | Email subject |
| `draftBody` | string |  | Email body content |
| `draftCc` | string |  | CC email address(es), comma-separated |
| `draftBcc` | string |  | BCC email address(es), comma-separated |
| `draftId` | string |  | ID of the draft |
| `draftUpdateTo` | string |  | Recipient email address(es), comma-separated |
| `draftUpdateSubject` | string |  | Email subject |
| `draftUpdateBody` | string |  | Email body content |
| `messageMaxResults` | number | 100 | Maximum number of messages to return |
| `messageQuery` | string |  | Query string for filtering results (Gmail search syntax) |
| `messageTo` | string |  | Recipient email address(es), comma-separated |
| `messageSubject` | string |  | Email subject |
| `messageBody` | string |  | Email body content |
| `messageCc` | string |  | CC email address(es), comma-separated |
| `messageBcc` | string |  | BCC email address(es), comma-separated |
| `messageId` | string |  | ID of the message |
| `messageAddLabelIds` | string |  | Comma-separated label IDs to add |
| `messageRemoveLabelIds` | string |  | Comma-separated label IDs to remove |
| `labelName` | string |  | Name of the label |
| `labelColor` | string |  | Color of the label (hex color code) |
| `labelId` | string |  | ID of the label |
| `threadMaxResults` | number | 100 | Maximum number of threads to return |
| `threadQuery` | string |  | Query string for filtering results (Gmail search syntax) |
| `threadId` | string |  | ID of the thread |
| `threadAddLabelIds` | string |  | Comma-separated label IDs to add |
| `threadRemoveLabelIds` | string |  | Comma-separated label IDs to remove |

</details>

---

### Google Calendar (`googleCalendarTool`)

**Version:** 1  
**Description:** Perform Google Calendar operations such as managing events, calendars, and checking availability  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (googleCalendarOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `calendarType` | options |  | Type of Google Calendar operation |
| `eventActions` | multiOptions |  | Actions to perform |
| `calendarActions` | multiOptions |  | Actions to perform |
| `freebusyActions` | multiOptions |  | Actions to perform |

<details>
<summary><b>Additional Parameters</b> (35 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `calendarId` | string | primary | Calendar ID (use "primary" for primary calendar) |
| `eventId` | string |  | Event ID for operations on specific events |
| `summary` | string |  | Event title/summary |
| `description` | string |  | Event description |
| `location` | string |  | Event location |
| `startDateTime` | string |  | Event start time (ISO 8601 format: 2023-12-25T10:00:00) |
| `endDateTime` | string |  | Event end time (ISO 8601 format: 2023-12-25T11:00:00) |
| `timeZone` | string |  | Time zone (e.g., America/New_York) |
| `allDay` | boolean |  | Whether this is an all-day event |
| `startDate` | string |  | Start date for all-day events (YYYY-MM-DD format) |
| `endDate` | string |  | End date for all-day events (YYYY-MM-DD format) |
| `attendees` | string |  | Comma-separated list of attendee emails |
| `sendUpdates` | options |  | Send Updates to attendees |
| `recurrence` | string |  | Recurrence rules (RRULE format) |
| `reminderMinutes` | number |  | Minutes before event to send reminder |
| `visibility` | options |  | Event visibility |
| `quickAddText` | string |  | Natural language text for quick event creation (e.g., "Lunch with John tomorrow at 12pm") |
| `timeMin` | string |  | Lower bound for event search (ISO 8601 format) |
| `timeMax` | string |  | Upper bound for event search (ISO 8601 format) |
| `maxResults` | number | 250 | Maximum number of events to return |
| `singleEvents` | boolean | True | Whether to expand recurring events into instances |
| `orderBy` | options |  | Order of events returned |
| `query` | string |  | Free text search terms |
| `calendarIdForCalendar` | string |  | Calendar ID for operations on specific calendars |
| `calendarSummary` | string |  | Calendar title/name |
| `calendarDescription` | string |  | Calendar description |
| `calendarLocation` | string |  | Calendar location |
| `calendarTimeZone` | string |  | Calendar time zone (e.g., America/New_York) |
| `showHidden` | boolean |  | Whether to show hidden calendars |
| `minAccessRole` | options |  | Minimum access role for calendar list |
| `freebusyTimeMin` | string |  | Lower bound for freebusy query (ISO 8601 format) |
| `freebusyTimeMax` | string |  | Upper bound for freebusy query (ISO 8601 format) |
| `calendarIds` | string |  | Comma-separated list of calendar IDs to check for free/busy info |
| `groupExpansionMax` | number |  | Maximum number of calendars for which FreeBusy information is to be provided |
| `calendarExpansionMax` | number |  | Maximum number of events that can be expanded for each calendar |

</details>

---

### Google Custom Search (`googleCustomSearch`)

**Version:** 1  
**Description:** Wrapper around Google Custom Search API - a real-time API to access Google search results  
**Base Classes:** `GoogleCustomSearchAPI`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (googleCustomSearchApi)

*No configurable inputs.*

---

### Google Docs (`googleDocsTool`)

**Version:** 1  
**Description:** Perform Google Docs operations such as creating, reading, updating, and deleting documents, as well as text manipulation  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (googleDocsOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `actions` | multiOptions |  | Actions to perform |

<details>
<summary><b>Additional Parameters</b> (10 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `documentId` | string |  | Document ID for operations on specific documents |
| `title` | string |  | Document title |
| `text` | string |  | Text content to insert or append |
| `index` | number | 1 | Index where to insert text or media (1-based, default: 1 for beginning) |
| `replaceText` | string |  | Text to replace |
| `newText` | string |  | New text to replace with |
| `matchCase` | boolean | False | Whether the search should be case-sensitive |
| `imageUrl` | string |  | URL of the image to insert |
| `rows` | number |  | Number of rows in the table |
| `columns` | number |  | Number of columns in the table |

</details>

---

### Google Drive (`googleDriveTool`)

**Version:** 1  
**Description:** Perform Google Drive operations such as managing files, folders, sharing, and searching  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (googleDriveOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `driveType` | options |  | Type of Google Drive operation |
| `fileActions` | multiOptions |  | Actions to perform on files |
| `folderActions` | multiOptions |  | Actions to perform on folders |
| `searchActions` | multiOptions |  | Search operations |
| `shareActions` | multiOptions |  | Sharing operations |

<details>
<summary><b>Additional Parameters</b> (31 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `fileId` | string |  | File ID for file operations |
| `fileId` | string |  | File ID for sharing operations |
| `folderId` | string |  | Folder ID for folder operations |
| `permissionId` | string |  | Permission ID to remove |
| `fileName` | string |  | Name of the file |
| `fileName` | string |  | Name of the folder |
| `fileContent` | string |  | Content of the file (for text files) |
| `mimeType` | string |  | MIME type of the file (e.g., text/plain, application/pdf) |
| `parentFolderId` | string |  | ID of the parent folder (comma-separated for multiple parents) |
| `parentFolderId` | string |  | ID of the parent folder for the new folder |
| `description` | string |  | File description |
| `description` | string |  | Folder description |
| `searchQuery` | string |  | Search query using Google Drive search syntax |
| `maxResults` | number | 10 | Maximum number of results to return (1-1000) |
| `maxResults` | number | 10 | Maximum number of results to return (1-1000) |
| `orderBy` | options |  | Sort order for file results |
| `orderBy` | options |  | Sort order for search results |
| `shareRole` | options |  | Permission role for sharing |
| `shareType` | options |  | Type of permission |
| `emailAddress` | string |  | Email address for user/group sharing |
| `domainName` | string |  | Domain name for domain sharing |
| `sendNotificationEmail` | boolean | True | Whether to send notification emails when sharing |
| `emailMessage` | string |  | Custom message to include in notification email |
| `includeItemsFromAllDrives` | boolean |  | Include items from all drives (shared drives) |
| `includeItemsFromAllDrives` | boolean |  | Include items from all drives (shared drives) |
| `supportsAllDrives` | boolean |  | Whether the application supports both My Drives and shared drives |
| `supportsAllDrives` | boolean |  | Whether the application supports both My Drives and shared drives |
| `supportsAllDrives` | boolean |  | Whether the application supports both My Drives and shared drives |
| `supportsAllDrives` | boolean |  | Whether the application supports both My Drives and shared drives |
| `fields` | string |  | Specific fields to include in response (e.g., "files(id,name,mimeType)") |
| `acknowledgeAbuse` | boolean |  | Acknowledge the risk of downloading known malware or abusive files |

</details>

---

### Google Sheets (`googleSheetsTool`)

**Version:** 1  
**Description:** Perform Google Sheets operations such as managing spreadsheets, reading and writing values  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (googleSheetsOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `sheetsType` | options |  | Type of Google Sheets operation |
| `spreadsheetActions` | multiOptions |  | Actions to perform on spreadsheets |
| `valuesActions` | multiOptions |  | Actions to perform on sheet values |

<details>
<summary><b>Additional Parameters</b> (12 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `spreadsheetId` | string |  | The ID of the spreadsheet |
| `title` | string |  | The title of the spreadsheet |
| `sheetCount` | number | 1 | Number of sheets to create |
| `range` | string |  | The range to read/write (e.g., A1:B2, Sheet1!A1:C10) |
| `ranges` | string |  | Comma-separated list of ranges for batch operations |
| `values` | string |  | JSON array of values to write (e.g., [["A1", "B1"], ["A2", "B2"]]) |
| `valueInputOption` | options | USER_ENTERED | How input data should be interpreted |
| `valueRenderOption` | options | FORMATTED_VALUE | How values should be represented in the output |
| `dateTimeRenderOption` | options | FORMATTED_STRING | How dates, times, and durations should be represented |
| `insertDataOption` | options | OVERWRITE | How data should be inserted |
| `includeGridData` | boolean | False | True if grid data should be returned |
| `majorDimension` | options | ROWS | The major dimension that results should use |

</details>

---

### Jira (`jiraTool`)

**Version:** 1  
**Description:** Perform Jira operations for issues, comments, and users  
**Base Classes:** `Jira`, `Tool`  

**Credential Required:** Connect Credential (jiraApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `jiraHost` | string |  | Host |
| `jiraType` | options |  | Type |
| `issueActions` | multiOptions |  | Issue Actions |
| `commentActions` | multiOptions |  | Comment Actions |
| `userActions` | multiOptions |  | User Actions |

<details>
<summary><b>Additional Parameters</b> (18 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `projectKey` | string |  | Project key for the issue |
| `issueType` | string |  | Type of issue to create |
| `issueSummary` | string |  | Issue summary/title |
| `issueDescription` | string |  | Issue description |
| `issuePriority` | string |  | Issue priority |
| `issueKey` | string |  | Issue key (e.g., PROJ-123) |
| `assigneeAccountId` | string |  | Account ID of the user to assign |
| `transitionId` | string |  | ID of the transition to execute |
| `jqlQuery` | string |  | JQL query for filtering issues |
| `issueMaxResults` | number | 50 | Maximum number of issues to return |
| `commentIssueKey` | string |  | Issue key for comment operations |
| `commentText` | string |  | Comment content |
| `commentId` | string |  | ID of the comment |
| `userQuery` | string |  | Query string for user search |
| `userAccountId` | string |  | User account ID |
| `userEmail` | string |  | User email address |
| `userDisplayName` | string |  | User display name |
| `userMaxResults` | number | 50 | Maximum number of users to return |

</details>

---

### JSON Path Extractor (`jsonPathExtractor`)

**Version:** 1  
**Description:** Extract values from JSON using path expressions  
**Base Classes:** `JSONPathExtractor`, `StructuredTool`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | string |  | Path to extract. Examples: data, user.name, items[0].id |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `returnNullOnError` | boolean | False | Return null instead of throwing error when extraction fails |

</details>

---

### Microsoft Outlook (`microsoftOutlook`)

**Version:** 1  
**Description:** Perform Microsoft Outlook operations for calendars, events, and messages  
**Base Classes:** `MicrosoftOutlook`, `Tool`  

**Credential Required:** Connect Credential (microsoftOutlookOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `outlookType` | options |  | Type |
| `calendarActions` | multiOptions |  | Calendar Actions |
| `messageActions` | multiOptions |  | Message Actions |

<details>
<summary><b>Additional Parameters</b> (44 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `maxResultsListCalendars` | number | 50 | Maximum number of calendars to return |
| `calendarIdGetCalendar` | string |  | ID of the calendar to retrieve |
| `calendarNameCreateCalendar` | string |  | Name of the calendar |
| `calendarIdUpdateCalendar` | string |  | ID of the calendar to update |
| `calendarNameUpdateCalendar` | string |  | New name of the calendar |
| `calendarIdDeleteCalendar` | string |  | ID of the calendar to delete |
| `calendarIdListEvents` | string |  | ID of the calendar (leave empty for primary calendar) |
| `maxResultsListEvents` | number | 50 | Maximum number of events to return |
| `startDateTimeListEvents` | string |  | Start date time filter in ISO format |
| `endDateTimeListEvents` | string |  | End date time filter in ISO format |
| `eventIdGetEvent` | string |  | ID of the event to retrieve |
| `subjectCreateEvent` | string |  | Subject/title of the event |
| `bodyCreateEvent` | string |  | Body/description of the event |
| `startDateTimeCreateEvent` | string |  | Start date and time in ISO format |
| `endDateTimeCreateEvent` | string |  | End date and time in ISO format |
| `timeZoneCreateEvent` | string | UTC | Time zone for the event |
| `locationCreateEvent` | string |  | Location of the event |
| `attendeesCreateEvent` | string |  | Comma-separated list of attendee email addresses |
| `eventIdUpdateEvent` | string |  | ID of the event to update |
| `subjectUpdateEvent` | string |  | New subject/title of the event |
| `eventIdDeleteEvent` | string |  | ID of the event to delete |
| `maxResultsListMessages` | number | 50 | Maximum number of messages to return |
| `filterListMessages` | string |  | Filter query (e.g., "isRead eq false") |
| `messageIdGetMessage` | string |  | ID of the message to retrieve |
| `toCreateDraftMessage` | string |  | Recipient email address(es), comma-separated |
| `subjectCreateDraftMessage` | string |  | Subject of the message |
| `bodyCreateDraftMessage` | string |  | Body content of the message |
| `ccCreateDraftMessage` | string |  | CC email address(es), comma-separated |
| `bccCreateDraftMessage` | string |  | BCC email address(es), comma-separated |
| `toSendMessage` | string |  | Recipient email address(es), comma-separated |
| `subjectSendMessage` | string |  | Subject of the message |
| `bodySendMessage` | string |  | Body content of the message |
| `messageIdUpdateMessage` | string |  | ID of the message to update |
| `isReadUpdateMessage` | boolean |  | Mark message as read/unread |
| `messageIdDeleteMessage` | string |  | ID of the message to delete |
| `messageIdCopyMessage` | string |  | ID of the message to copy |
| `destinationFolderIdCopyMessage` | string |  | ID of the destination folder |
| `messageIdMoveMessage` | string |  | ID of the message to move |
| `destinationFolderIdMoveMessage` | string |  | ID of the destination folder |
| `messageIdReplyMessage` | string |  | ID of the message to reply to |
| `replyBodyReplyMessage` | string |  | Reply message body |
| `messageIdForwardMessage` | string |  | ID of the message to forward |
| `forwardToForwardMessage` | string |  | Email address(es) to forward to, comma-separated |
| `forwardCommentForwardMessage` | string |  | Additional comment to include with forward |

</details>

---

### Microsoft Teams (`microsoftTeams`)

**Version:** 1  
**Description:** Perform Microsoft Teams operations for channels, chats, and chat messages  
**Base Classes:** `MicrosoftTeams`, `Tool`  

**Credential Required:** Connect Credential (microsoftTeamsOAuth2)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `teamsType` | options |  | Type |
| `channelActions` | multiOptions |  | Channel Actions |
| `chatActions` | multiOptions |  | Chat Actions |
| `chatMessageActions` | multiOptions |  | Chat Message Actions |

<details>
<summary><b>Additional Parameters</b> (52 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `teamIdListChannels` | string |  | ID of the team to list channels from |
| `maxResultsListChannels` | number | 50 | Maximum number of channels to return |
| `teamIdGetChannel` | string |  | ID of the team that contains the channel |
| `channelIdGetChannel` | string |  | ID of the channel to retrieve |
| `teamIdCreateChannel` | string |  | ID of the team to create the channel in |
| `displayNameCreateChannel` | string |  | Display name of the channel |
| `descriptionCreateChannel` | string |  | Description of the channel |
| `membershipTypeCreateChannel` | options | standard | Type of channel membership |
| `teamIdUpdateChannel` | string |  | ID of the team that contains the channel |
| `channelIdUpdateChannel` | string |  | ID of the channel to update |
| `displayNameUpdateChannel` | string |  | New display name of the channel |
| `teamIdDeleteChannel` | string |  | ID of the team that contains the channel |
| `channelIdDeleteChannel` | string |  | ID of the channel to delete or archive |
| `teamIdChannelMembers` | string |  | ID of the team that contains the channel |
| `channelIdChannelMembers` | string |  | ID of the channel |
| `userIdChannelMember` | string |  | ID of the user to add or remove |
| `maxResultsListChats` | number | 50 | Maximum number of chats to return |
| `chatIdGetChat` | string |  | ID of the chat to retrieve |
| `chatTypeCreateChat` | options | group | Type of chat to create |
| `topicCreateChat` | string |  | Topic/subject of the chat (for group chats) |
| `membersCreateChat` | string |  | Comma-separated list of user IDs to add to the chat |
| `chatIdUpdateChat` | string |  | ID of the chat to update |
| `topicUpdateChat` | string |  | New topic/subject of the chat |
| `chatIdDeleteChat` | string |  | ID of the chat to delete |
| `chatIdChatMembers` | string |  | ID of the chat |
| `userIdChatMember` | string |  | ID of the user to add or remove |
| `chatIdPinMessage` | string |  | ID of the chat |
| `messageIdPinMessage` | string |  | ID of the message to pin or unpin |
| `chatChannelIdListMessages` | string |  | ID of the chat or channel to list messages from |
| `teamIdListMessages` | string |  | ID of the team (required for channel messages) |
| `maxResultsListMessages` | number | 50 | Maximum number of messages to return |
| `chatChannelIdGetMessage` | string |  | ID of the chat or channel |
| `teamIdGetMessage` | string |  | ID of the team (required for channel messages) |
| `messageIdGetMessage` | string |  | ID of the message to retrieve |
| `chatChannelIdSendMessage` | string |  | ID of the chat or channel to send message to |
| `teamIdSendMessage` | string |  | ID of the team (required for channel messages) |
| `messageBodySendMessage` | string |  | Content of the message |
| `contentTypeSendMessage` | options | text | Content type of the message |
| `chatChannelIdUpdateMessage` | string |  | ID of the chat or channel |
| `teamIdUpdateMessage` | string |  | ID of the team (required for channel messages) |
| `messageIdUpdateMessage` | string |  | ID of the message to update |
| `chatChannelIdDeleteMessage` | string |  | ID of the chat or channel |
| `teamIdDeleteMessage` | string |  | ID of the team (required for channel messages) |
| `messageIdDeleteMessage` | string |  | ID of the message to delete |
| `chatChannelIdReplyMessage` | string |  | ID of the chat or channel |
| `teamIdReplyMessage` | string |  | ID of the team (required for channel messages) |
| `messageIdReplyMessage` | string |  | ID of the message to reply to |
| `replyBodyReplyMessage` | string |  | Content of the reply |
| `chatChannelIdReaction` | string |  | ID of the chat or channel |
| `teamIdReaction` | string |  | ID of the team (required for channel messages) |
| `messageIdReaction` | string |  | ID of the message to react to |
| `reactionTypeSetReaction` | options | like | Type of reaction to set |

</details>

---

### OpenAPI Toolkit (`openAPIToolkit`)

**Version:** 2.1  
**Description:** Load OpenAPI specification, and converts each API endpoint to a tool  
**Base Classes:** `OpenAPIToolkit`, `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `inputType` | options | file | Choose how to provide the OpenAPI specification |
| `openApiFile` | file |  | Upload your OpenAPI specification file (YAML or JSON) |
| `openApiLink` | string |  | Provide a link to your OpenAPI specification (YAML or JSON) |
| `selectedServer` | asyncOptions |  | Select which server to use for API calls |
| `selectedEndpoints` | asyncMultiOptions |  | Select which endpoints to expose as tools |
| `returnDirect` | boolean |  | Return the output of the tool directly to the user |
| `removeNulls` | boolean |  | Remove all keys with null values from the parsed arguments |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `headers` | json |  | Request headers to be sent with the API request. For example, {"Authorization": "Bearer token"} |
| `customCode` | code | const fetch = require('node-fetch');
const url = $url;
const options = $options;

try {
	const response = await fetch(url, options);
	const resp = await response.json();
	return JSON.stringify(resp);
} catch (error) {
	console.error(error);
	return '';
}
 | Custom code to return the output of the tool. The code should be a function that takes in the input  |

</details>

---

### QueryEngine Tool (`queryEngineToolLlamaIndex`)

**Version:** 2  
**Description:** Tool used to invoke query engine  
**Base Classes:** `QueryEngineTool`, `Tool_LlamaIndex`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `baseQueryEngine` | BaseQueryEngine |  | Base QueryEngine |
| `toolName` | string |  | Tool name must be small capital letter with underscore. Ex: my_tool |
| `toolDesc` | string |  | Tool Description |

---

### Requests Delete (`requestsDelete`)

**Version:** 1  
**Description:** Execute HTTP DELETE requests  
**Base Classes:** `RequestsDelete`, `DynamicStructuredTool`, `StructuredTool`, `Runnable`, `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `requestsDeleteUrl` | string |  | URL |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `requestsDeleteName` | string | requests_delete | Name of the tool |
| `requestsDeleteDescription` | string | Use this when you need to execute a DELETE request to remove data from a website. | Describe to LLM when it should use this tool |
| `requestsDeleteHeaders` | string |  | Headers |
| `requestsDeleteQueryParamsSchema` | code |  | Description of the available query params to enable LLM to figure out which query params to use |
| `requestsDeleteMaxOutputLength` | number | 2000 | Max length of the output. Remove this if you want to return the entire response |

</details>

---

### Requests Get (`requestsGet`)

**Version:** 2  
**Description:** Execute HTTP GET requests  
**Base Classes:** `RequestsGet`, `DynamicStructuredTool`, `StructuredTool`, `Runnable`, `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `requestsGetUrl` | string |  | URL |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `requestsGetName` | string | requests_get | Name of the tool |
| `requestsGetDescription` | string | Use this when you need to execute a GET request to get data from a website. | Describe to LLM when it should use this tool |
| `requestsGetHeaders` | string |  | Headers |
| `requestsGetQueryParamsSchema` | code |  | Description of the available query params to enable LLM to figure out which query params to use |
| `requestsGetMaxOutputLength` | number | 2000 | Max length of the output. Remove this if you want to return the entire response |

</details>

---

### Requests Post (`requestsPost`)

**Version:** 2  
**Description:** Execute HTTP POST requests  
**Base Classes:** `RequestsPost`, `DynamicStructuredTool`, `StructuredTool`, `Runnable`, `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `requestsPostUrl` | string |  | URL |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `requestsPostName` | string | requests_post | Name of the tool |
| `requestsPostDescription` | string | Use this when you want to execute a POST request to create or update a resource. | Describe to LLM when it should use this tool |
| `requestsPostHeaders` | string |  | Headers |
| `requestPostBody` | string |  | JSON body for the POST request. This will override the body generated by the LLM |
| `requestsPostBodySchema` | code |  | Description of the available body params to enable LLM to figure out which body params to use |
| `requestsPostMaxOutputLength` | number | 2000 | Max length of the output. Remove this if you want to return the entire response |

</details>

---

### Requests Put (`requestsPut`)

**Version:** 1  
**Description:** Execute HTTP PUT requests  
**Base Classes:** `RequestsPut`, `DynamicStructuredTool`, `StructuredTool`, `Runnable`, `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `requestsPutUrl` | string |  | URL |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `requestsPutName` | string | requests_put | Name of the tool |
| `requestsPutDescription` | string | Use this when you want to execute a PUT request to update or replace a resource. | Describe to LLM when it should use this tool |
| `requestsPutHeaders` | string |  | Headers |
| `requestPutBody` | string |  | JSON body for the PUT request. This will override the body generated by the LLM |
| `requestsPutBodySchema` | code |  | Description of the available body params to enable LLM to figure out which body params to use |
| `requestsPutMaxOutputLength` | number | 2000 | Max length of the output. Remove this if you want to return the entire response |

</details>

---

### Retriever Tool (`retrieverTool`)

**Version:** 3  
**Description:** Use a retriever as allowed tool for agent  
**Base Classes:** `RetrieverTool`, `DynamicTool`, `Tool`, `StructuredTool`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | string |  | Retriever Name |
| `description` | string |  | When should agent uses to retrieve documents |
| `retriever` | BaseRetriever |  | Retriever |
| `returnSourceDocuments` | boolean |  | Return Source Documents |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `retrieverToolMetadataFilter` | json |  | Add additional metadata filter on top of the existing filter from vector store |

</details>

---

### SearXNG (`searXNG`)

**Version:** 3  
**Description:** Wrapper around SearXNG - a free internet metasearch engine  
**Base Classes:** `SearXNG`, `Tool`, `StructuredTool`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `apiBase` | string | http://localhost:8080 | Base URL |
| `toolName` | string | searxng-search | Tool Name |
| `toolDescription` | string | A meta search engine. Useful for when you need to answer questions about current events. Input should be a search query. Output is a JSON array of the query results | Tool Description |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `headers` | json |  | Custom headers for the request |
| `format` | options | json | Format of the response. You need to enable search formats in settings.yml. Refer to <a target="_blan |
| `categories` | string |  | Comma separated list, specifies the active search categories. (see <a target="_blank" href="https:// |
| `engines` | string |  | Comma separated list, specifies the active search engines. (see <a target="_blank" href="https://doc |
| `language` | string |  | Code of the language. |
| `pageno` | number |  | Search page number. |
| `time_range` | string |  | Time range of search for engines which support it. See if an engine supports time range search in th |
| `safesearch` | number |  | Filter search results of engines which support safe search. See if an engine supports safe search in |

</details>

---

### SearchApi (`searchAPI`)

**Version:** 1  
**Description:** Real-time API for accessing Google Search data  
**Base Classes:** `SearchAPI`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (searchApi)

*No configurable inputs.*

---

### Serp API (`serpAPI`)

**Version:** 1  
**Description:** Wrapper around SerpAPI - a real-time API to access Google search results  
**Base Classes:** `SerpAPI`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (serpApi)

*No configurable inputs.*

---

### Serper (`serper`)

**Version:** 1  
**Description:** Wrapper around Serper.dev - Google Search API  
**Base Classes:** `Serper`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (serperApi)

*No configurable inputs.*

---

### StripeAgentTool (`stripeAgentTool`)

**Version:** 1  
**Description:** Use Stripe Agent function calling for financial transactions  
**Base Classes:** `stripeAgentTool`, `Tool`  

**Credential Required:** Connect Credential (stripeApi)

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `paymentLinks` | multiOptions |  | Payment Links |
| `products` | multiOptions |  | Products |
| `prices` | multiOptions |  | Prices |
| `balance` | multiOptions |  | Balance |
| `invoiceItems` | multiOptions |  | Invoice Items |
| `invoices` | multiOptions |  | Invoices |
| `customers` | multiOptions |  | Customers |

</details>

---

### Tavily API (`tavilyAPI`)

**Version:** 1.2  
**Description:** Wrapper around TavilyAPI - A specialized search engine designed for LLMs and AI agents  
**Base Classes:** `TavilyAPI`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (tavilyApi)

<details>
<summary><b>Additional Parameters</b> (12 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topic` | options | general | The category of the search. News for real-time updates, general for broader searches |
| `searchDepth` | options | basic | The depth of the search. Advanced costs 2 API Credits, basic costs 1 |
| `chunksPerSource` | number | 3 | Number of content chunks per source (1-3). Only for advanced search |
| `maxResults` | number | 5 | Maximum number of search results (0-20) |
| `timeRange` | options |  | Time range to filter results |
| `days` | number | 7 | Number of days back from current date (only for news topic) |
| `includeAnswer` | boolean | False | Include an LLM-generated answer to the query |
| `includeRawContent` | boolean | False | Include cleaned and parsed HTML content of each result |
| `includeImages` | boolean | False | Include image search results |
| `includeImageDescriptions` | boolean | False | Include descriptive text for each image |
| `includeDomains` | string |  | Comma-separated list of domains to include in results |
| `excludeDomains` | string |  | Comma-separated list of domains to exclude from results |

</details>

---

### Web Browser (`webBrowser`)

**Version:** 1  
**Description:** Gives agent the ability to visit a website and extract information  
**Base Classes:** `WebBrowser`, `Tool`, `StructuredTool`, `Runnable`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `model` | BaseLanguageModel |  | Language Model |
| `embeddings` | Embeddings |  | Embeddings |

---

### Web Scraper Tool (`webScraperTool`)

**Version:** 1.1  
**Description:** Scrapes web pages recursively by following links OR by fetching URLs from the default sitemap.  
**Base Classes:** `Tool`, `Tool`, `StructuredTool`, `Runnable`  

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `scrapeMode` | options | recursive | Select discovery method: 'Recursive' follows links found on pages (uses Max Depth). 'Sitemap' tries  |
| `maxDepth` | number | 1 | Maximum levels of links to follow (e.g., 1 = only the initial URL, 2 = initial URL + links found on  |
| `maxPages` | number | 10 | Maximum total number of pages to scrape, regardless of mode or depth. Stops when this limit is reach |
| `timeoutS` | number | 60 | Maximum time in seconds to wait for each page request to complete. Accepts decimals (e.g., 0.5). Def |
| `description` | string |  | Custom description of what the tool does. This is for LLM to determine when to use this tool. Overri |

</details>

---

### WolframAlpha (`wolframAlpha`)

**Version:** 1  
**Description:** Wrapper around WolframAlpha - a powerful computational knowledge engine  
**Base Classes:** `WolframAlpha`, `Tool`, `StructuredTool`, `Runnable`  

**Credential Required:** Connect Credential (wolframAlphaAppId)

*No configurable inputs.*

---

## Tools (MCP) (8)

### Brave Search MCP (`braveSearchMCP`)

**Version:** 1  
**Description:** MCP server that integrates the Brave Search API - a real-time API to access web search capabilities  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (braveSearchApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `mcpActions` | asyncMultiOptions |  | Available Actions |

---

### Custom MCP (`customMCP`)

**Version:** 1.1  
**Description:** Custom MCP Config  
**Base Classes:** `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `mcpServerConfig` | code |  | MCP Server Config |
| `mcpActions` | asyncMultiOptions |  | Available Actions |

---

### Github MCP (`githubMCP`)

**Version:** 1  
**Description:** MCP Server for the GitHub API  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (githubApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `mcpActions` | asyncMultiOptions |  | Available Actions |

---

### PostgreSQL MCP (`postgreSQLMCP`)

**Version:** 1  
**Description:** MCP server that provides read-only access to PostgreSQL databases  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (PostgresUrl)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `mcpActions` | asyncMultiOptions |  | Available Actions |

---

### Sequential Thinking MCP (`sequentialThinkingMCP`)

**Version:** 1  
**Description:** MCP server that provides a tool for dynamic and reflective problem-solving through a structured thinking process  
**Base Classes:** `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `mcpActions` | asyncMultiOptions |  | Available Actions |

---

### Slack MCP (`slackMCP`)

**Version:** 1  
**Description:** MCP Server for the Slack API  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (slackApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `mcpActions` | asyncMultiOptions |  | Available Actions |

---

### Supergateway MCP (`supergatewayMCP`)

**Version:** 1  
**Description:** Runs MCP stdio-based servers over SSE (Server-Sent Events) or WebSockets (WS)  
**Base Classes:** `Tool`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `arguments` | string |  | Arguments to pass to the supergateway server. Refer to the <a href="https://github.com/supercorp-ai/ |
| `mcpActions` | asyncMultiOptions |  | Available Actions |

---

### Teradata MCP (`teradataMCP`)

**Version:** 1  
**Description:** MCP Server for Teradata (remote HTTP streamable)  
**Base Classes:** `Tool`  

**Credential Required:** Connect Credential (teradataTD2Auth, teradataBearerToken)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `mcpUrl` | string |  | URL of your Teradata MCP server |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `bearerToken` | string |  | Optional to override Default set credentials |
| `mcpActions` | asyncMultiOptions |  | Available Actions |

---

## Utilities (5)

### Custom JS Function (`customFunction`)

**Version:** 3  
**Description:** Execute custom javascript function  
**Base Classes:** `CustomFunction`, `Utilities`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `functionInputVariables` | json |  | Input variables can be used in the function with prefix $. For example: $var |
| `functionName` | string |  | Function Name |
| `tools` | Tool |  | Tools can be used in the function with $tools.{tool_name}.invoke(args) |
| `javascriptFunction` | code |  | Javascript Function |

---

### Get Variable (`getVariable`)

**Version:** 2  
**Description:** Get variable that was saved using Set Variable node  
**Base Classes:** `GetVariable`, `Utilities`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `variableName` | string |  | Variable Name |

---

### IfElse Function (`ifElseFunction`)

**Version:** 2  
**Description:** Split flows based on If Else javascript functions  
**Base Classes:** `IfElseFunction`, `Utilities`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `functionInputVariables` | json |  | Input variables can be used in the function with prefix $. For example: $var |
| `functionName` | string |  | IfElse Name |
| `ifFunction` | code | if ("hello" == "hello") {
    return true;
} | Function must return a value |
| `elseFunction` | code | return false; | Function must return a value |

---

### Set Variable (`setVariable`)

**Version:** 2.1  
**Description:** Set variable which can be retrieved at a later stage. Variable is only available during runtime.  
**Base Classes:** `SetVariable`, `Utilities`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `input` | string \| number \| boolean \| json \| array |  | Input |
| `variableName` | string |  | Variable Name |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `showOutput` | boolean |  | Show the output result in the Prediction API response |

</details>

---

### Sticky Note (`stickyNote`)

**Version:** 2  
**Description:** Add a sticky note  
**Base Classes:** `StickyNote`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `note` | string |  |  |

---

## Vector Stores (26)

### Astra (`Astra`)

**Version:** 2  
**Description:** Upsert embedded data and perform similarity or mmr search upon query using DataStax Astra DB, a serverless vector database that’s perfect for managing mission-critical AI workloads  
**Base Classes:** `Astra`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (AstraDBApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `astraNamespace` | string |  | Namespace |
| `astraCollection` | string |  | Collection |
| `vectorDimension` | number |  | Dimension used for storing vector embedding |
| `similarityMetric` | string |  | cosine | euclidean | dot_product |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `searchType` | options | similarity | Search Type |
| `fetchK` | number |  | Number of initial documents to fetch for MMR reranking. Default to 20. Used only when the search typ |
| `lambda` | number |  | Number between 0 and 1 that determines the degree of diversity among the results, where 0 correspond |

</details>

---

### Chroma (`chroma`)

**Version:** 2  
**Description:** Upsert embedded data and perform similarity search upon query using Chroma, an open-source embedding database  
**Base Classes:** `Chroma`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (chromaApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `recordManager` | RecordManager |  | Keep track of the record to prevent duplication |
| `collectionName` | string |  | Collection Name |
| `chromaURL` | string |  | Chroma URL |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `chromaMetadataFilter` | json |  | Chroma Metadata Filter |
| `topK` | number |  | Number of top results to fetch. Default to 4 |

</details>

---

### Couchbase (`couchbase`)

**Version:** 1  
**Description:** Upsert embedded data and load existing index using Couchbase, a award-winning distributed NoSQL database  
**Base Classes:** `Couchbase`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (couchbaseApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `bucketName` | string |  | Bucket Name |
| `scopeName` | string |  | Scope Name |
| `collectionName` | string |  | Collection Name |
| `indexName` | string |  | Index Name |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `textKey` | string | text | Name of the field (column) that contains the actual content |
| `embeddingKey` | string | embedding | Name of the field (column) that contains the Embedding |
| `couchbaseMetadataFilter` | json |  | Couchbase Metadata Filter |
| `topK` | number |  | Number of top results to fetch. Default to 4 |

</details>

---

### Document Store (Vector) (`documentStoreVS`)

**Version:** 1  
**Description:** Search and retrieve documents from Document Store  
**Base Classes:** `DocumentStoreVS`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `selectedStore` | asyncOptions |  | Select Store |

---

### Elasticsearch (`elasticsearch`)

**Version:** 2  
**Description:** Upsert embedded data and perform similarity search upon query using Elasticsearch, a distributed search and analytics engine  
**Base Classes:** `Elasticsearch`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (elasticsearchApi, elasticSearchUserPassword)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `recordManager` | RecordManager |  | Keep track of the record to prevent duplication |
| `indexName` | string |  | Index Name |

<details>
<summary><b>Additional Parameters</b> (2 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `similarity` | options | l2_norm | Similarity measure used in Elasticsearch. |

</details>

---

### Faiss (`faiss`)

**Version:** 1  
**Description:** Upsert embedded data and perform similarity search upon query using Faiss library from Meta  
**Base Classes:** `Faiss`, `VectorStoreRetriever`, `BaseRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `basePath` | string |  | Path to load faiss.index file |

<details>
<summary><b>Additional Parameters</b> (1 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number |  | Number of top results to fetch. Default to 4 |

</details>

---

### AWS Kendra (`kendra`)

**Version:** 1  
**Description:** Use AWS Kendra's intelligent search service for document retrieval and semantic search  
**Base Classes:** `Kendra`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** AWS Credential (awsApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `region` | asyncOptions | us-east-1 | Region |
| `indexId` | string |  | The ID of your AWS Kendra index |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `fileUpload` | boolean |  | Allow file upload on the chat |
| `topK` | number |  | Number of top results to fetch. Default to 10 |
| `attributeFilter` | json |  | Optional filter to apply when retrieving documents |

</details>

---

### Meilisearch (`meilisearch`)

**Version:** 1  
**Description:** Upsert embedded data and perform similarity search upon query using Meilisearch hybrid search functionality  
**Base Classes:** `BaseRetriever`  

**Credential Required:** Connect Credential (meilisearchApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `host` | string |  | This is the URL for the desired Meilisearch instance, the URL must not end with a '/' |
| `indexUid` | string |  | UID for the index to answer from |
| `deleteIndex` | boolean |  | Delete Index if exists |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `K` | number |  | number of top searches to return as context, default is 4 |
| `semanticRatio` | number |  | percentage of semantic reasoning in meilisearch hybrid search, default is 0.75 |
| `searchFilter` | string |  | search filter to apply on searchable attributes |

</details>

---

### In-Memory Vector Store (`memoryVectorStore`)

**Version:** 1
**Description:** In-memory vectorstore that stores embeddings and does an exact, linear search for the most similar embeddings.
**Base Classes:** `Memory`, `VectorStoreRetriever`, `BaseRetriever`

> **RUNTIME CONSTRAINT:** A document loader node (e.g. `plainText`, `textFile`, `pdfFile`) MUST
> be wired to the `document` input anchor. Without a document source the node cannot initialize
> and Flowise returns "Expected a Runnable" (HTTP 500) on every prediction. Always include a
> document loader when using this node in a RAG flow.

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `topK` | number |  | Number of top results to fetch. Default to 4 |

---

### Milvus (`milvus`)

**Version:** 2.1  
**Description:** Upsert embedded data and perform similarity search upon query using Milvus, world's most advanced open-source vector database  
**Base Classes:** `Milvus`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (milvusAuth)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `milvusServerUrl` | string |  | Milvus Server URL |
| `milvusCollection` | string |  | Milvus Collection Name |
| `milvusPartition` | string | _default | Milvus Partition Name |

<details>
<summary><b>Additional Parameters</b> (9 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `fileUpload` | boolean |  | Allow file upload on the chat |
| `milvusTextField` | string |  | Milvus Text Field |
| `milvusFilter` | string |  | Filter data with a simple string query. Refer Milvus <a target="_blank" href="https://milvus.io/blog |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `secure` | boolean |  | Enable secure connection to Milvus server |
| `clientPemPath` | string |  | Path to the client PEM file |
| `clientKeyPath` | string |  | Path to the client key file |
| `caPemPath` | string |  | Path to the root PEM file |
| `serverName` | string |  | Server name for the secure connection |

</details>

---

### MongoDB Atlas (`mongoDBAtlas`)

**Version:** 1  
**Description:** Upsert embedded data and perform similarity or mmr search upon query using MongoDB Atlas, a managed cloud mongodb database  
**Base Classes:** `MongoDB Atlas`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (mongoDBUrlApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `databaseName` | string |  | Database |
| `collectionName` | string |  | Collection Name |
| `indexName` | string |  | Index Name |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `textKey` | string | text | Name of the field (column) that contains the actual content |
| `embeddingKey` | string | embedding | Name of the field (column) that contains the Embedding |
| `mongoMetadataFilter` | json |  | Mongodb Metadata Filter |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `searchType` | options | similarity | Search Type |
| `fetchK` | number |  | Number of initial documents to fetch for MMR reranking. Default to 20. Used only when the search typ |
| `lambda` | number |  | Number between 0 and 1 that determines the degree of diversity among the results, where 0 correspond |

</details>

---

### OpenSearch (`openSearch`)

**Version:** 4  
**Description:** Upsert embedded data and perform similarity search upon query using OpenSearch, an open-source, all-in-one vector database  
**Base Classes:** `OpenSearch`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (openSearchUrl)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `indexName` | string |  | Index Name |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `engine` | options | lucene | Vector search engine. Use "lucene" or "faiss" for OpenSearch 3.x+, "nmslib" for older versions |
| `spaceType` | options | l2 | Distance metric for similarity search |

</details>

---

### Pinecone (`pinecone`)

**Version:** 5  
**Description:** Upsert embedded data and perform similarity or mmr search using Pinecone, a leading fully managed hosted vector database  
**Base Classes:** `Pinecone`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (pineconeApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `recordManager` | RecordManager |  | Keep track of the record to prevent duplication |
| `pineconeIndex` | string |  | Pinecone Index |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `pineconeNamespace` | string |  | Pinecone Namespace |
| `fileUpload` | boolean |  | Allow file upload on the chat |
| `pineconeTextKey` | string |  | The key in the metadata for storing text. Default to `text` |
| `pineconeMetadataFilter` | json |  | Pinecone Metadata Filter |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `searchType` | options | similarity | Search Type |
| `fetchK` | number |  | Number of initial documents to fetch for MMR reranking. Default to 20. Used only when the search typ |
| `lambda` | number |  | Number between 0 and 1 that determines the degree of diversity among the results, where 0 correspond |

</details>

---

### Pinecone (`pineconeLlamaIndex`)

**Version:** 1  
**Description:** Upsert embedded data and perform similarity search upon query using Pinecone, a leading fully managed hosted vector database  
**Base Classes:** `Pinecone`, `VectorIndexRetriever`  

**Credential Required:** Connect Credential (pineconeApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `model` | BaseChatModel_LlamaIndex |  | Chat Model |
| `embeddings` | BaseEmbedding_LlamaIndex |  | Embeddings |
| `pineconeIndex` | string |  | Pinecone Index |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `pineconeNamespace` | string |  | Pinecone Namespace |
| `pineconeMetadataFilter` | json |  | Pinecone Metadata Filter |
| `topK` | number |  | Number of top results to fetch. Default to 4 |

</details>

---

### Postgres (`postgres`)

**Version:** 7.1  
**Description:** Upsert embedded data and perform similarity search upon query using pgvector on Postgres  
**Base Classes:** `Postgres`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (PostgresApi)

**Required Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `host` | string |  | Host |
| `database` | string |  | Database |

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `recordManager` | RecordManager |  | Keep track of the record to prevent duplication |
| `port` | number |  | Port |

<details>
<summary><b>Additional Parameters</b> (9 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `ssl` | boolean |  | Use SSL to connect to Postgres |
| `tableName` | string |  | Table Name |
| `distanceStrategy` | options | cosine | Strategy for calculating distances between vectors |
| `fileUpload` | boolean |  | Allow file upload on the chat |
| `batchSize` | number |  | Upsert in batches of size N |
| `additionalConfig` | json |  | Additional Configuration |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `pgMetadataFilter` | json |  | Postgres Metadata Filter |
| `contentColumnName` | string |  | Column name to store the text content (PGVector Driver only, others use pageContent) |

</details>

---

### Qdrant (`qdrant`)

**Version:** 5  
**Description:** Upsert embedded data and perform similarity search upon query using Qdrant, a scalable open source vector database written in Rust  
**Base Classes:** `Qdrant`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (qdrantApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `recordManager` | RecordManager |  | Keep track of the record to prevent duplication |
| `qdrantServerUrl` | string |  | Qdrant Server URL |
| `qdrantCollection` | string |  | Qdrant Collection Name |

<details>
<summary><b>Additional Parameters</b> (9 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `fileUpload` | boolean |  | Allow file upload on the chat |
| `qdrantVectorDimension` | number | 1536 | Vector Dimension |
| `contentPayloadKey` | string | content | The key for storing text. Default to `content` |
| `metadataPayloadKey` | string | metadata | The key for storing metadata. Default to `metadata` |
| `batchSize` | number |  | Upsert in batches of size N |
| `qdrantSimilarity` | options | Cosine | Similarity measure used in Qdrant. |
| `qdrantCollectionConfiguration` | json |  | Refer to <a target="_blank" href="https://qdrant.tech/documentation/concepts/collections">collection |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `qdrantFilter` | json |  | Only return points which satisfy the conditions |

</details>

---

### Redis (`redis`)

**Version:** 1  
**Description:** Upsert embedded data and perform similarity search upon query using Redis, an open source, in-memory data structure store  
**Base Classes:** `Redis`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (redisCacheUrlApi, redisCacheApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `indexName` | string |  | Index Name |
| `replaceIndex` | boolean | False | Selecting this option will delete the existing index and recreate a new one when upserting |

<details>
<summary><b>Additional Parameters</b> (4 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `contentKey` | string | content | Name of the field (column) that contains the actual content |
| `metadataKey` | string | metadata | Name of the field (column) that contains the metadata of the document |
| `vectorKey` | string | content_vector | Name of the field (column) that contains the vector |
| `topK` | number |  | Number of top results to fetch. Default to 4 |

</details>

---

### SimpleStore (`simpleStoreLlamaIndex`)

**Version:** 1  
**Description:** Upsert embedded data to local path and perform similarity search  
**Base Classes:** `SimpleVectorStore`, `VectorIndexRetriever`  

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `model` | BaseChatModel_LlamaIndex |  | Chat Model |
| `embeddings` | BaseEmbedding_LlamaIndex |  | Embeddings |
| `basePath` | string |  | Path to store persist embeddings indexes with persistence. If not specified, default to same path wh |
| `topK` | number |  | Number of top results to fetch. Default to 4 |

---

### SingleStore (`singlestore`)

**Version:** 1  
**Description:** Upsert embedded data and perform similarity search upon query using SingleStore, a fast and distributed cloud relational database  
**Base Classes:** `SingleStore`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (singleStoreApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `host` | string |  | Host |
| `database` | string |  | Database |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `tableName` | string |  | Table Name |
| `contentColumnName` | string |  | Content Column Name |
| `vectorColumnName` | string |  | Vector Column Name |
| `metadataColumnName` | string |  | Metadata Column Name |
| `topK` | number |  | Top K |

</details>

---

### Supabase (`supabase`)

**Version:** 4  
**Description:** Upsert embedded data and perform similarity or mmr search upon query using Supabase via pgvector extension  
**Base Classes:** `Supabase`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (supabaseApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `recordManager` | RecordManager |  | Keep track of the record to prevent duplication |
| `supabaseProjUrl` | string |  | Supabase Project URL |
| `tableName` | string |  | Table Name |
| `queryName` | string |  | Query Name |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `supabaseMetadataFilter` | json |  | Supabase Metadata Filter |
| `supabaseRPCFilter` | string |  | Query builder-style filtering. If this is set, will override the metadata filter. Refer <a href="htt |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `searchType` | options | similarity | Search Type |
| `fetchK` | number |  | Number of initial documents to fetch for MMR reranking. Default to 20. Used only when the search typ |
| `lambda` | number |  | Number between 0 and 1 that determines the degree of diversity among the results, where 0 correspond |

</details>

---

### Upstash Vector (`upstash`)

**Version:** 2  
**Description:** Upsert data as embedding or string and perform similarity search with Upstash, the leading serverless data platform  
**Base Classes:** `Upstash`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (upstashVectorApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `recordManager` | RecordManager |  | Keep track of the record to prevent duplication |

<details>
<summary><b>Additional Parameters</b> (3 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `fileUpload` | boolean |  | Allow file upload on the chat |
| `upstashMetadataFilter` | string |  | Upstash Metadata Filter |
| `topK` | number |  | Number of top results to fetch. Default to 4 |

</details>

---

### Vectara (`vectara`)

**Version:** 2  
**Description:** Upsert embedded data and perform similarity search upon query using Vectara, a LLM-powered search-as-a-service  
**Base Classes:** `Vectara`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (vectaraApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `file` | file |  | File to upload to Vectara. Supported file types: https://docs.vectara.com/docs/api-reference/indexin |

<details>
<summary><b>Additional Parameters</b> (7 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `filter` | string |  | Filter to apply to Vectara metadata. Refer to the <a target="_blank" href="https://docs.flowiseai.co |
| `sentencesBefore` | number | 2 | Number of sentences to fetch before the matched sentence. Defaults to 2. |
| `sentencesAfter` | number | 2 | Number of sentences to fetch after the matched sentence. Defaults to 2. |
| `lambda` | number | 0 | Enable hybrid search to improve retrieval accuracy by adjusting the balance (from 0 to 1) between ne |
| `topK` | number |  | Number of top results to fetch. Defaults to 5 |
| `mmrK` | number |  | Number of top results to fetch for MMR. Defaults to 50 |
| `mmrDiversityBias` | number |  | The diversity bias to use for MMR. This is a value between 0.0 and 1.0Values closer to 1.0 optimize  |

</details>

---

### Vectara Upload File (`vectaraUpload`)

**Version:** 1  
**Description:** Upload files to Vectara  
**Base Classes:** `Vectara`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (vectaraApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `file` | file |  | File to upload to Vectara. Supported file types: https://docs.vectara.com/docs/api-reference/indexin |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `filter` | string |  | Filter to apply to Vectara metadata. Refer to the <a target="_blank" href="https://docs.flowiseai.co |
| `sentencesBefore` | number |  | Number of sentences to fetch before the matched sentence. Defaults to 2. |
| `sentencesAfter` | number |  | Number of sentences to fetch after the matched sentence. Defaults to 2. |
| `lambda` | number |  | Improves retrieval accuracy by adjusting the balance (from 0 to 1) between neural search and keyword |
| `topK` | number |  | Number of top results to fetch. Defaults to 4 |

</details>

---

### Weaviate (`weaviate`)

**Version:** 4  
**Description:** Upsert embedded data and perform similarity or mmr search using Weaviate, a scalable open-source vector database  
**Base Classes:** `Weaviate`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (weaviateApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `recordManager` | RecordManager |  | Keep track of the record to prevent duplication |
| `weaviateScheme` | options | https | Weaviate Scheme |
| `weaviateHost` | string |  | Weaviate Host |
| `weaviateIndex` | string |  | Weaviate Index |

<details>
<summary><b>Additional Parameters</b> (8 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `weaviateTextKey` | string |  | Weaviate Text Key |
| `weaviateMetadataKeys` | string |  | Weaviate Metadata Keys |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `weaviateFilter` | json |  | Weaviate Search Filter |
| `searchType` | options | similarity | Search Type |
| `fetchK` | number |  | Number of initial documents to fetch for MMR reranking. Default to 20. Used only when the search typ |
| `lambda` | number |  | Number between 0 and 1 that determines the degree of diversity among the results, where 0 correspond |
| `alpha` | number |  | Number between 0 and 1 that determines the weighting of keyword (BM25) portion of the hybrid search. |

</details>

---

### Zep Collection - Open Source (`zep`)

**Version:** 2  
**Description:** Upsert embedded data and perform similarity or mmr search upon query using Zep, a fast and scalable building block for LLM apps  
**Base Classes:** `Zep`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (zepMemoryApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `embeddings` | Embeddings |  | Embeddings |
| `baseURL` | string | http://127.0.0.1:8000 | Base URL |
| `zepCollection` | string |  | Zep Collection |

<details>
<summary><b>Additional Parameters</b> (6 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `zepMetadataFilter` | json |  | Zep Metadata Filter |
| `dimension` | number | 1536 | Embedding Dimension |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `searchType` | options | similarity | Search Type |
| `fetchK` | number |  | Number of initial documents to fetch for MMR reranking. Default to 20. Used only when the search typ |
| `lambda` | number |  | Number between 0 and 1 that determines the degree of diversity among the results, where 0 correspond |

</details>

---

### Zep Collection - Cloud (`zepCloud`)

**Version:** 2  
**Description:** Upsert embedded data and perform similarity or mmr search upon query using Zep, a fast and scalable building block for LLM apps  
**Base Classes:** `Zep`, `VectorStoreRetriever`, `BaseRetriever`  

**Credential Required:** Connect Credential (zepMemoryApi)

**Optional Inputs:**

| Name | Type | Default | Description |
|---|---|---|---|
| `document` | Document |  | Document |
| `zepCollection` | string |  | Zep Collection |

<details>
<summary><b>Additional Parameters</b> (5 params)</summary>

| Name | Type | Default | Description |
|---|---|---|---|
| `zepMetadataFilter` | json |  | Zep Metadata Filter |
| `topK` | number |  | Number of top results to fetch. Default to 4 |
| `searchType` | options | similarity | Search Type |
| `fetchK` | number |  | Number of initial documents to fetch for MMR reranking. Default to 20. Used only when the search typ |
| `lambda` | number |  | Number between 0 and 1 that determines the degree of diversity among the results, where 0 correspond |

</details>

---
