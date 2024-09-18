export default async function handler(req, res) {
    if (req.method === 'POST') {
        const { code } = req.body;

        // Use environment variables for Strava credentials and the webhook URL
        const clientId = process.env.STRAVA_CLIENT_ID;
        const clientSecret = process.env.STRAVA_CLIENT_SECRET;
        const webhookUrl = process.env.BOTPRESS_WEBHOOK_URL;

        try {
            // Send HTTP POST request to the webhook
            const response = await fetch(webhookUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    auth_code: code,
                    client_id: clientId,
                    client_secret: clientSecret,
                    conversationId: 'conv_01J82FTZNZEP72YQFKANNZNMFK'
                })
            });

            const data = await response.json();
            
            // Return success message
            res.status(200).json({ success: true, data });
        } catch (error) {
            console.error('Error sending POST request:', error);
            res.status(500).json({ success: false, message: 'Failed to send POST request', error });
        }
    } else {
        res.status(405).json({ message: 'Method not allowed' });
    }
}
